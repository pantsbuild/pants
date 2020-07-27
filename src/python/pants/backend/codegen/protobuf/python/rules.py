# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.subsystems.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import ProtobufSources
from pants.backend.python.target_types import PythonSources
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.strip_source_roots import representative_path_from_address
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, Digest, MergeDigests, RemovePrefix, Snapshot
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import GeneratedSources, GenerateSourcesRequest, Sources, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest


class GeneratePythonFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSources
    output = PythonSources


@rule(desc="Generate Python from Protobuf")
async def generate_python_from_protobuf(
    request: GeneratePythonFromProtobufRequest, protoc: Protoc
) -> GeneratedSources:
    download_protoc_request = Get[DownloadedExternalTool](
        ExternalToolRequest, protoc.get_request(Platform.current)
    )

    output_dir = "_generated_files"
    # TODO(#9650): replace this with a proper intrinsic to create empty directories.
    create_output_dir_request = Get[ProcessResult](
        Process(
            ("/bin/mkdir", output_dir),
            description=f"Create the directory {output_dir}",
            output_directories=(output_dir,),
        )
    )

    # Protoc needs all transitive dependencies on `protobuf_libraries` to work properly. It won't
    # actually generate those dependencies; it only needs to look at their .proto files to work
    # with imports.
    transitive_targets = await Get[TransitiveTargets](Addresses([request.protocol_target.address]))
    all_sources_request = Get[SourceFiles](
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in transitive_targets.closure),
            for_sources_types=(ProtobufSources,),
            # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
            # for Protobuf imports to be discoverable.
            strip_source_roots=True,
        )
    )
    stripped_target_sources_request = Get[SourceFiles](
        AllSourceFilesRequest([request.protocol_target[ProtobufSources]], strip_source_roots=True)
    )

    (
        downloaded_protoc_binary,
        create_output_dir_result,
        all_sources,
        stripped_target_sources,
    ) = await MultiGet(
        download_protoc_request,
        create_output_dir_request,
        all_sources_request,
        stripped_target_sources_request,
    )

    input_digest = await Get[Digest](
        MergeDigests(
            (
                all_sources.snapshot.digest,
                downloaded_protoc_binary.digest,
                create_output_dir_result.output_digest,
            )
        )
    )

    result = await Get[ProcessResult](
        Process(
            (
                downloaded_protoc_binary.exe,
                "--python_out",
                output_dir,
                *stripped_target_sources.snapshot.files,
            ),
            input_digest=input_digest,
            description=f"Generating Python sources from {request.protocol_target.address}.",
            output_directories=(output_dir,),
        )
    )

    # We must do some path manipulation on the output digest for it to look like normal sources,
    # including adding back the original source root.
    normalized_digest = await Get[Digest](RemovePrefix(result.output_digest, output_dir))
    source_root = await Get[SourceRoot](
        SourceRootRequest,
        SourceRootRequest.for_file(
            representative_path_from_address(request.protocol_target.address)
        ),
    )
    source_root_restored = (
        await Get(Snapshot, AddPrefix(normalized_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, normalized_digest)
    )
    return GeneratedSources(source_root_restored)


def rules():
    return [
        generate_python_from_protobuf,
        UnionRule(GenerateSourcesRequest, GeneratePythonFromProtobufRequest),
        SubsystemRule(Protoc),
    ]
