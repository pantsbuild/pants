# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.scala.scalapbc import ScalaPBSubsystem
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufSourceField,
)
from pants.backend.scala.target_types import ScalaSourceField
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    InjectDependenciesRequest,
    InjectedDependencies,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import MaterializedClasspath, MaterializedClasspathRequest
from pants.jvm.resolve.jvm_tool import JvmToolLockfileRequest, JvmToolLockfileSentinel
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GenerateScalaFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = ScalaSourceField


class ScalapbcToolLockfileSentinel(JvmToolLockfileSentinel):
    options_scope = ScalaPBSubsystem.options_scope


@rule(desc="Generate Scala from Protobuf", level=LogLevel.DEBUG)
async def generate_scala_from_protobuf(
    request: GenerateScalaFromProtobufRequest,
    protoc: Protoc,
    scalapbc: ScalaPBSubsystem,
    jdk_setup: JdkSetup,
    bash: BashBinary,
) -> GeneratedSources:
    output_dir = "_generated_files"
    toolcp_relpath = "__toolcp"

    downloaded_protoc_binary, tool_classpath, empty_output_dir, transitive_targets = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, protoc.get_request(Platform.current)),
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                lockfiles=(scalapbc.resolved_lockfile(),),
            ),
        ),
        Get(Digest, CreateDigest([Directory(output_dir)])),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.protocol_target.address])),
    )

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_sources_stripped, target_sources_stripped, protoc_gen_scala_digest = await MultiGet(
        Get(
            StrippedSourceFiles,
            SourceFilesRequest(
                tgt[ProtobufSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ProtobufSourceField)
            ),
        ),
        Get(
            StrippedSourceFiles, SourceFilesRequest([request.protocol_target[ProtobufSourceField]])
        ),
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        "protoc-gen-scala",
                        textwrap.dedent(
                            f"""\
                                       #!{bash.path}
                                       exec {' '.join(jdk_setup.args(bash, tool_classpath.classpath_entries(toolcp_relpath))[1:])} scalapb.ScalaPbCodeGenerator "$@"
                                       """
                        ).encode(),
                        is_executable=True,
                    )
                ]
            ),
        ),
    )

    unmerged_digests = [
        all_sources_stripped.snapshot.digest,
        downloaded_protoc_binary.digest,
        protoc_gen_scala_digest,
        empty_output_dir,
    ]

    immutable_input_digests = {
        **jdk_setup.immutable_input_digests,
        toolcp_relpath: tool_classpath.digest,
    }

    input_digest = await Get(Digest, MergeDigests(unmerged_digests))

    args = [
        downloaded_protoc_binary.exe,
        "--plugin=protoc-gen-scala=./protoc-gen-scala",
        "--scala_out",
        output_dir,
        *target_sources_stripped.snapshot.files,
    ]

    # TODO: Consider using nailgun or how to use the GraalVM-built native image for `scalapbc`.
    result = await Get(
        ProcessResult,
        Process(
            args,
            input_digest=input_digest,
            immutable_input_digests=immutable_input_digests,
            description=f"Generating Scala sources from {request.protocol_target.address}.",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
            env=jdk_setup.env,
            append_only_caches=jdk_setup.append_only_caches,
        ),
    )

    normalized_digest, source_root = await MultiGet(
        Get(Digest, RemovePrefix(result.output_digest, output_dir)),
        Get(SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(normalized_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, normalized_digest)
    )
    return GeneratedSources(source_root_restored)


class InjectScalaProtobufDependencies(InjectDependenciesRequest):
    inject_for = ProtobufDependenciesField


@rule
async def inject_scalapb_dependencies(
    _: InjectScalaProtobufDependencies, scalapb: ScalaPBSubsystem
) -> InjectedDependencies:
    addresses = await Get(Addresses, UnparsedAddressInputs, scalapb.runtime_dependencies)
    return InjectedDependencies(addresses)


@rule
async def generate_scalapbc_lockfile_request(
    _: ScalapbcToolLockfileSentinel,
    tool: ScalaPBSubsystem,
) -> JvmToolLockfileRequest:
    return JvmToolLockfileRequest.from_tool(tool)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateScalaFromProtobufRequest),
        UnionRule(JvmToolLockfileSentinel, ScalapbcToolLockfileSentinel),
    ]
