# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.protobuf.target_types import ProtobufSources
from pants.backend.python.target_types import PythonSources
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address, AddressInput
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.graph import parse_dependencies_field
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    GeneratedSources,
    GenerateSourcesRequest,
    RegisteredTargetTypes,
    Sources,
    Subtargets,
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import GlobalOptions
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


class GeneratePythonFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSources
    output = PythonSources


@rule(desc="Generate Python from Protobuf", level=LogLevel.DEBUG)
async def generate_python_from_protobuf(
    request: GeneratePythonFromProtobufRequest,
    protoc: Protoc,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
    global_options: GlobalOptions,
) -> GeneratedSources:
    download_protoc_request = Get(
        DownloadedExternalTool, ExternalToolRequest, protoc.get_request(Platform.current)
    )

    output_dir = "_generated_files"
    create_output_dir_request = Get(Digest, CreateDigest([Directory(output_dir)]))

    # Protoc needs all transitive dependencies on `protobuf_libraries` to work properly. It won't
    # actually generate those dependencies; it only needs to look at their .proto files to work
    # with imports.
    # TODO(#10917): This monstrosity is because we are not able to use
    # `await Get(TransitiveTargets`) without causing rule graph issues. So, we copy a hacky
    # implementation of the rules to resolve direct deps + transitive deps. This implementation is
    # much less robust:
    #
    #    - Does not use dependency injection.
    #    - Does not use dependency inference.
    #    - Always places dependencies on subtargets, and isn't as careful about avoiding
    #      self-cycles.
    #    - Worse performance, as this doesn't batch as efficiently.
    #
    # Normally, these restrictions would be a non-starter, but because we are solely looking for
    # transitive dependencies on Protobuf libraries, these hacks are tolerable for now.
    visited: OrderedSet[Target] = OrderedSet()
    queued = OrderedSet([request.protocol_target])
    while queued:
        tgt = queued.pop()
        visited.add(tgt)

        # Recreate the DependenciesRequest rule.
        parsed_deps = parse_dependencies_field(
            tgt.get(Dependencies),
            subproject_roots=global_options.options.subproject_roots,
            registered_target_types=registered_target_types.types,
            union_membership=union_membership,
        )
        included_wrapped_targets = await MultiGet(
            Get(WrappedTarget, AddressInput, ai) for ai in parsed_deps.addresses
        )
        ignored_wrapped_targets = await MultiGet(
            Get(WrappedTarget, AddressInput, ai) for ai in parsed_deps.ignored_addresses
        )
        subtargets = await Get(Subtargets, Address, tgt.address.maybe_convert_to_base_target())
        direct_dependencies = FrozenOrderedSet(
            wrapped_t.target for wrapped_t in included_wrapped_targets
        ) | FrozenOrderedSet(subtargets.subtargets) - FrozenOrderedSet(
            wrapped_t.target for wrapped_t in ignored_wrapped_targets
        )

        queued.update(direct_dependencies.difference(visited))
    all_targets = visited

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_stripped_sources_request = Get(
        StrippedSourceFiles,
        SourceFilesRequest(
            (tgt.get(Sources) for tgt in all_targets),
            for_sources_types=(ProtobufSources,),
        ),
    )
    target_stripped_sources_request = Get(
        StrippedSourceFiles, SourceFilesRequest([request.protocol_target[ProtobufSources]])
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

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                all_sources_stripped.snapshot.digest,
                downloaded_protoc_binary.digest,
                empty_output_dir,
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
