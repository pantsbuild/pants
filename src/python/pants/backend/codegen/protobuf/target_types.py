# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    GeneratedTargets,
    GenerateTargetsRequest,
    Sources,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    generate_file_level_targets,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.docutil import doc_url


# NB: We subclass Dependencies so that specific backends can add dependency injection rules to
# Protobuf targets.
class ProtobufDependencies(Dependencies):
    pass


class ProtobufSources(Sources):
    default = ("*.proto",)
    expected_file_extensions = (".proto",)


class ProtobufGrpcToggle(BoolField):
    alias = "grpc"
    default = False
    help = "Whether to generate gRPC code or not."


class ProtobufLibrary(Target):
    alias = "protobuf_library"
    core_fields = (*COMMON_TARGET_FIELDS, ProtobufDependencies, ProtobufSources, ProtobufGrpcToggle)
    help = f"Protobuf files used to generate various languages.\n\nSee f{doc_url('protobuf')}."


class GenerateProtobufLibraryFromProtobufLibrary(GenerateTargetsRequest):
    target_class = ProtobufLibrary


@rule
async def generate_protobuf_library_from_protobuf_library(
    request: GenerateProtobufLibraryFromProtobufLibrary, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(SourcesPaths, SourcesPathsRequest(request.target[ProtobufSources]))
    return generate_file_level_targets(
        ProtobufLibrary, request.target, paths.files, union_membership
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateProtobufLibraryFromProtobufLibrary),
    )
