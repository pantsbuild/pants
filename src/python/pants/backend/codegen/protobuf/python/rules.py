# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import PurePath

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.protobuf.target_types import ProtobufSources
from pants.backend.python.target_types import PythonSources
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.strip_source_roots import StrippedSourceFiles
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, Digest, MergeDigests, RemovePrefix, Snapshot
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest, Sources, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GeneratePythonFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSources
    output = PythonSources


@rule(desc="Generate Python from Protobuf")
async def generate_python_from_protobuf(
    request: GeneratePythonFromProtobufRequest, protoc: Protoc
) -> GeneratedSources:
    download_protoc_request = Get(
        DownloadedExternalTool, ExternalToolRequest, protoc.get_request(Platform.current)
    )

    output_dir = "_generated_files"
    # TODO(#9650): replace this with a proper intrinsic to create empty directories.
    create_output_dir_request = Get(
        ProcessResult,
        Process(
            ("/bin/mkdir", output_dir),
            description=f"Create the directory {output_dir}",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
        ),
    )

    # Protoc needs all transitive dependencies on `protobuf_libraries` to work properly. It won't
    # actually generate those dependencies; it only needs to look at their .proto files to work
    # with imports.
    transitive_targets = await Get(TransitiveTargets, Addresses([request.protocol_target.address]))
    all_sources_request = Get(
        SourceFiles,
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in transitive_targets.closure),
            for_sources_types=(ProtobufSources,),
        ),
    )
    unstripped_target_sources_request = Get(
        SourceFiles, AllSourceFilesRequest([request.protocol_target[ProtobufSources]]),
    )

    (
        downloaded_protoc_binary,
        create_output_dir_result,
        all_sources_unstripped,
        target_sources_unstripped,
    ) = await MultiGet(
        download_protoc_request,
        create_output_dir_request,
        all_sources_request,
        unstripped_target_sources_request,
    )

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_sources_stripped, target_sources_stripped = await MultiGet(
        Get(StrippedSourceFiles, SourceFiles, all_sources_unstripped),
        Get(StrippedSourceFiles, SourceFiles, target_sources_unstripped),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                all_sources_stripped.snapshot.digest,
                downloaded_protoc_binary.digest,
                create_output_dir_result.output_digest,
            )
        ),
    )

    result = await Get(
        ProcessResult,
        Process(
            (
                downloaded_protoc_binary.exe,
                "--python_out",
                output_dir,
                *target_sources_stripped.snapshot.files,
            ),
            input_digest=input_digest,
            description=f"Generating Python sources from {request.protocol_target.address}.",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
        ),
    )

    # We must do some path manipulation on the output digest for it to look like normal sources,
    # including adding back a source root.
    py_source_root = request.protocol_target.get(PythonSourceRootField).value
    if py_source_root:
        # Verify that the python source root specified by the target is in fact a source root.
        source_root_request = SourceRootRequest(PurePath(py_source_root))
    else:
        # The target didn't specify a python source root, so use the protobuf_library's source root.
        source_root_request = SourceRootRequest.for_target(request.protocol_target)

    normalized_digest, source_root = await MultiGet(
        Get(Digest, RemovePrefix(result.output_digest, output_dir)),
        Get(SourceRoot, SourceRootRequest, source_root_request),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(normalized_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, normalized_digest)
    )
    return GeneratedSources(source_root_restored)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GeneratePythonFromProtobufRequest),
    ]
