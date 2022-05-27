# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.codegen.protobuf.java import dependency_inference
from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.java.target_types import JavaSourceField
from pants.backend.python.util_rules import pex
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.target_types import PrefixedJvmJdkField, PrefixedJvmResolveField
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GenerateJavaFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = JavaSourceField


@rule(desc="Generate Java from Protobuf", level=LogLevel.DEBUG)
async def generate_java_from_protobuf(
    request: GenerateJavaFromProtobufRequest,
    protoc: Protoc,
) -> GeneratedSources:
    download_protoc_request = Get(
        DownloadedExternalTool, ExternalToolRequest, protoc.get_request(Platform.current)
    )

    output_dir = "_generated_files"
    create_output_dir_request = Get(Digest, CreateDigest([Directory(output_dir)]))

    # Protoc needs all transitive dependencies on `protobuf_source` to work properly. It won't
    # actually generate those dependencies; it only needs to look at their .proto files to work
    # with imports.
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([request.protocol_target.address])
    )

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_stripped_sources_request = Get(
        StrippedSourceFiles,
        SourceFilesRequest(
            tgt[ProtobufSourceField]
            for tgt in transitive_targets.closure
            if tgt.has_field(ProtobufSourceField)
        ),
    )
    target_stripped_sources_request = Get(
        StrippedSourceFiles, SourceFilesRequest([request.protocol_target[ProtobufSourceField]])
    )

    (
        downloaded_protoc_binary,
        empty_output_dir,
        all_sources_stripped,
        target_sources_stripped,
    ) = await MultiGet(
        download_protoc_request,
        create_output_dir_request,
        all_stripped_sources_request,
        target_stripped_sources_request,
    )

    unmerged_digests = [
        all_sources_stripped.snapshot.digest,
        downloaded_protoc_binary.digest,
        empty_output_dir,
    ]
    input_digest = await Get(Digest, MergeDigests(unmerged_digests))

    argv = [downloaded_protoc_binary.exe, "--java_out", output_dir]

    argv.extend(target_sources_stripped.snapshot.files)
    result = await Get(
        ProcessResult,
        Process(
            argv,
            input_digest=input_digest,
            description=f"Generating Java sources from {request.protocol_target.address}.",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
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


def rules():
    return [
        *collect_rules(),
        *pex.rules(),
        *dependency_inference.rules(),
        UnionRule(GenerateSourcesRequest, GenerateJavaFromProtobufRequest),
        ProtobufSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        ProtobufSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
    ]
