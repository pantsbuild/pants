# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import os
from pathlib import PurePath

from pants.backend.codegen.protobuf import protoc
from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.protobuf.python.grpc_python_plugin import GrpcPythonPlugin
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    PythonProtobufGrpclibPlugin,
    PythonProtobufMypyPlugin,
    PythonProtobufSubsystem,
)
from pants.backend.codegen.protobuf.target_types import ProtobufGrpcToggleField, ProtobufSourceField
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import (
    VenvPexRequest,
    create_venv_pex,
    determine_venv_pex_resolve_info,
)
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.engine.fs import AddPrefix, CreateDigest, Directory, MergeDigests, RemovePrefix
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.intrinsics import create_digest, digest_to_snapshot, merge_digests, remove_prefix
from pants.engine.platform import Platform
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRootRequest, get_source_root
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class GeneratePythonFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = PythonSourceField


@rule(desc="Generate Python from Protobuf", level=LogLevel.DEBUG)
async def generate_python_from_protobuf(
    request: GeneratePythonFromProtobufRequest,
    protoc: Protoc,
    grpc_python_plugin: GrpcPythonPlugin,
    python_protobuf_subsystem: PythonProtobufSubsystem,
    python_protobuf_mypy_plugin: PythonProtobufMypyPlugin,
    python_protobuf_grpclib_plugin: PythonProtobufGrpclibPlugin,
    pex_environment: PexEnvironment,
    platform: Platform,
) -> GeneratedSources:
    download_protoc_request = download_external_tool(protoc.get_request(platform))

    output_dir = "_generated_files"
    create_output_dir_request = create_digest(CreateDigest([Directory(output_dir)]))

    # Protoc needs all transitive dependencies on `protobuf_libraries` to work properly. It won't
    # actually generate those dependencies; it only needs to look at their .proto files to work
    # with imports.
    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest([request.protocol_target.address]), **implicitly()
    )

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_stripped_sources_request = strip_source_roots(
        **implicitly(
            SourceFilesRequest(
                tgt[ProtobufSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ProtobufSourceField)
            )
        )
    )
    target_stripped_sources_request = strip_source_roots(
        **implicitly(SourceFilesRequest([request.protocol_target[ProtobufSourceField]]))
    )

    (
        downloaded_protoc_binary,
        empty_output_dir,
        all_sources_stripped,
        target_sources_stripped,
    ) = await concurrently(
        download_protoc_request,
        create_output_dir_request,
        all_stripped_sources_request,
        target_stripped_sources_request,
    )

    grpc_enabled = request.protocol_target.get(ProtobufGrpcToggleField).value
    protoc_relpath = "__protoc"
    unmerged_digests = [
        all_sources_stripped.snapshot.digest,
        empty_output_dir,
    ]

    pyi_gen_option = "pyi_out:" if python_protobuf_subsystem.generate_type_stubs else ""
    protoc_argv = [
        os.path.join(protoc_relpath, downloaded_protoc_binary.exe),
        f"--python_out={pyi_gen_option}{output_dir}",
    ]

    complete_pex_env = pex_environment.in_sandbox(working_directory=None)

    if python_protobuf_subsystem.mypy_plugin:
        protoc_gen_mypy_script = "protoc-gen-mypy"
        protoc_gen_mypy_grpc_script = "protoc-gen-mypy_grpc"
        mypy_request = python_protobuf_mypy_plugin.to_pex_request()
        mypy_pex = await create_venv_pex(
            VenvPexRequest(
                pex_request=mypy_request,
                complete_pex_env=complete_pex_env,
                bin_names=[protoc_gen_mypy_script],
            ),
            **implicitly(),
        )
        protoc_argv.extend(
            [
                f"--plugin=protoc-gen-mypy={mypy_pex.bin[protoc_gen_mypy_script].argv0}",
                "--mypy_out",
                output_dir,
            ]
        )

        if grpc_enabled and python_protobuf_subsystem.grpcio_plugin:
            mypy_pex_info = await determine_venv_pex_resolve_info(mypy_pex)

            # In order to generate stubs for gRPC code, we need mypy-protobuf 2.0 or above.
            mypy_protobuf_info = mypy_pex_info.find("mypy-protobuf")
            if mypy_protobuf_info and mypy_protobuf_info.version.major >= 2:
                # TODO: Use `pex_path` once VenvPex stores a Pex field.
                mypy_pex = await create_venv_pex(
                    VenvPexRequest(
                        pex_request=mypy_request,
                        complete_pex_env=complete_pex_env,
                        bin_names=[protoc_gen_mypy_script, protoc_gen_mypy_grpc_script],
                    ),
                    **implicitly(),
                )
                protoc_argv.extend(
                    [
                        f"--plugin=protoc-gen-mypy_grpc={mypy_pex.bin[protoc_gen_mypy_grpc_script].argv0}",
                        "--mypy_grpc_out",
                        output_dir,
                    ]
                )
        unmerged_digests.append(mypy_pex.digest)

    if grpc_enabled:
        if not (
            python_protobuf_subsystem.grpcio_plugin or python_protobuf_subsystem.grpclib_plugin
        ):
            logger.warning(
                """
            No Python grpc plugins have been enabled. Make sure to enable at least one of the
            following under the [python-protobuf] configuration: grpcio_plugin, grpclib_plugin.
            """
            )

        if python_protobuf_subsystem.grpcio_plugin:
            downloaded_grpc_plugin = await download_external_tool(
                grpc_python_plugin.get_request(platform)
            )
            unmerged_digests.append(downloaded_grpc_plugin.digest)
            protoc_argv.extend(
                [f"--plugin=protoc-gen-grpc={downloaded_grpc_plugin.exe}", "--grpc_out", output_dir]
            )

        if python_protobuf_subsystem.grpclib_plugin:
            protoc_gen_grpclib_script = "protoc-gen-grpclib_python"
            grpclib_request = python_protobuf_grpclib_plugin.to_pex_request()
            grpclib_pex = await create_venv_pex(
                VenvPexRequest(
                    pex_request=grpclib_request,
                    complete_pex_env=complete_pex_env,
                    bin_names=[protoc_gen_grpclib_script],
                ),
                **implicitly(),
            )
            unmerged_digests.append(grpclib_pex.digest)
            protoc_argv.extend(
                [
                    f"--plugin=protoc-gen-grpclib_python={grpclib_pex.bin[protoc_gen_grpclib_script].argv0}",
                    "--grpclib_python_out",
                    output_dir,
                ]
            )

    input_digest = await merge_digests(MergeDigests(unmerged_digests))
    protoc_argv.extend(target_sources_stripped.snapshot.files)
    result = await execute_process_or_raise(
        **implicitly(
            Process(
                protoc_argv,
                input_digest=input_digest,
                immutable_input_digests={
                    protoc_relpath: downloaded_protoc_binary.digest,
                },
                description=f"Generating Python sources from {request.protocol_target.address}.",
                level=LogLevel.DEBUG,
                output_directories=(output_dir,),
                append_only_caches=complete_pex_env.append_only_caches,
            )
        ),
    )

    # We must do some path manipulation on the output digest for it to look like normal sources,
    # including adding back a source root.
    py_source_root = request.protocol_target.get(PythonSourceRootField).value
    if py_source_root:
        # Verify that the python source root specified by the target is in fact a source root.
        source_root_request = SourceRootRequest(PurePath(py_source_root))
    else:
        # The target didn't specify a python source root, so use the protobuf_source's source root.
        source_root_request = SourceRootRequest.for_target(request.protocol_target)

    normalized_digest, source_root = await concurrently(
        remove_prefix(RemovePrefix(result.output_digest, output_dir)),
        get_source_root(source_root_request),
    )

    source_root_restored = (
        await digest_to_snapshot(**implicitly(AddPrefix(normalized_digest, source_root.path)))
        if source_root.path != "."
        else await digest_to_snapshot(normalized_digest)
    )
    return GeneratedSources(source_root_restored)


def rules():
    return [
        *collect_rules(),
        *pex.rules(),
        UnionRule(GenerateSourcesRequest, GeneratePythonFromProtobufRequest),
        *protoc.rules(),
        UnionRule(ExportableTool, GrpcPythonPlugin),
    ]
