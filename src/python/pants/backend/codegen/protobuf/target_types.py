# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    BoolField,
    Dependencies,
    GeneratedTargets,
    GenerateTargetsRequest,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    Targets,
    generate_file_based_overrides_field_help_message,
    generate_file_level_targets,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import FilesNotFoundBehavior
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel


# NB: We subclass Dependencies so that specific backends can add dependency injection rules to
# `protobuf_source` targets.
class ProtobufDependenciesField(Dependencies):
    pass


class ProtobufGrpcToggleField(BoolField):
    alias = "grpc"
    default = False
    help = "Whether to generate gRPC code or not."


class AllProtobufTargets(Targets):
    pass


@rule(desc="Find all Protobuf targets in project", level=LogLevel.DEBUG)
def find_all_protobuf_targets(targets: AllTargets) -> AllProtobufTargets:
    return AllProtobufTargets(tgt for tgt in targets if tgt.has_field(ProtobufSourceField))


# -----------------------------------------------------------------------------------------------
# `protobuf_source` target
# -----------------------------------------------------------------------------------------------


class ProtobufSourceField(SingleSourceField):
    expected_file_extensions = (".proto",)


class ProtobufSourceTarget(Target):
    alias = "protobuf_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ProtobufDependenciesField,
        ProtobufSourceField,
        ProtobufGrpcToggleField,
    )
    help = (
        "A single Protobuf file used to generate various languages.\n\n"
        f"See {doc_url('protobuf')}."
    )


# -----------------------------------------------------------------------------------------------
# `protobuf_sources` target generator
# -----------------------------------------------------------------------------------------------


class ProtobufSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.proto",)
    expected_file_extensions = (".proto",)


class ProtobufSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        ProtobufSourceTarget.alias,
        (
            "overrides={\n"
            '  "foo.proto": {"grpc": True]},\n'
            '  "bar.proto": {"description": "our user model"]},\n'
            '  ("foo.proto", "bar.proto"): {"tags": ["overridden"]},\n'
            "}"
        ),
    )


class ProtobufSourcesGeneratorTarget(Target):
    alias = "protobuf_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ProtobufDependenciesField,
        ProtobufSourcesGeneratingSourcesField,
        ProtobufGrpcToggleField,
        ProtobufSourcesOverridesField,
    )
    help = "Generate a `protobuf_source` target for each file in the `sources` field."


class GenerateTargetsFromProtobufSources(GenerateTargetsRequest):
    generate_from = ProtobufSourcesGeneratorTarget


@rule
async def generate_targets_from_protobuf_sources(
    request: GenerateTargetsFromProtobufSources,
    files_not_found_behavior: FilesNotFoundBehavior,
    protoc: Protoc,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[ProtobufSourcesGeneratingSourcesField])
    )

    all_overrides = {}
    overrides_field = request.generator[OverridesField]
    if overrides_field.value:
        _all_override_paths = await MultiGet(
            Get(Paths, PathGlobs, path_globs)
            for path_globs in overrides_field.to_path_globs(files_not_found_behavior)
        )
        all_overrides = overrides_field.flatten_paths(
            dict(zip(_all_override_paths, overrides_field.value.values()))
        )

    return generate_file_level_targets(
        ProtobufSourceTarget,
        request.generator,
        sources_paths.files,
        union_membership,
        add_dependencies_on_all_siblings=not protoc.dependency_inference,
        overrides=all_overrides,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromProtobufSources),
    )
