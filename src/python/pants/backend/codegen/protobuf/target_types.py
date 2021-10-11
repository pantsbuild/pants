# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    GeneratedTargets,
    GenerateTargetsRequest,
    MultipleSourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    generate_file_level_targets,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.docutil import doc_url, git_url


# NB: We subclass Dependencies so that specific backends can add dependency injection rules to
# `protobuf_source` targets.
class ProtobufDependenciesField(Dependencies):
    pass


class ProtobufGrpcToggleField(BoolField):
    alias = "grpc"
    default = False
    help = "Whether to generate gRPC code or not."


# -----------------------------------------------------------------------------------------------
# `protobuf_source` target
# -----------------------------------------------------------------------------------------------


class ProtobufSourcesField(MultipleSourcesField):
    expected_file_extensions = (".proto",)
    expected_num_files = 1
    required = True


class ProtobufSourceTarget(Target):
    alias = "protobuf_sources"  # TODO(#12954): rename to `protobuf_source` when ready. Update `help` too.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ProtobufDependenciesField,
        ProtobufSourcesField,
        ProtobufGrpcToggleField,
    )
    help = f"A Protobuf file used to generate various languages.\n\nSee f{doc_url('protobuf')}."

    deprecated_alias = "protobuf_library"
    deprecated_alias_removal_version = "2.9.0.dev0"


# -----------------------------------------------------------------------------------------------
# `protobuf_sources` target generator
# -----------------------------------------------------------------------------------------------


class ProtobufSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.proto",)
    expected_file_extensions = (".proto",)


class ProtobufSourcesGeneratorTarget(Target):
    alias = "protobuf_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ProtobufDependenciesField,
        ProtobufSourcesGeneratingSourcesField,
        ProtobufGrpcToggleField,
    )
    help = f"Protobuf files used to generate various languages.\n\nSee f{doc_url('protobuf')}."

    deprecated_alias = "protobuf_library"
    deprecated_alias_removal_version = "2.9.0.dev0"
    deprecated_alias_removal_hint = (
        "Use `protobuf_sources` instead, which behaves the same.\n\n"
        "To automate fixing this, download "
        f"{git_url('build-support/migration-support/rename_targets_pants28.py')}, then run "
        "`python3 rename_targets_pants28.py --help` for instructions."
    )


class GenerateTargetsFromProtobufSources(GenerateTargetsRequest):
    generate_from = ProtobufSourcesGeneratorTarget


@rule
async def generate_targets_from_protobuf_sources(
    request: GenerateTargetsFromProtobufSources,
    protoc: Protoc,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[ProtobufSourcesGeneratingSourcesField])
    )
    return generate_file_level_targets(
        ProtobufSourceTarget,
        request.generator,
        paths.files,
        union_membership,
        add_dependencies_on_all_siblings=not protoc.dependency_inference,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromProtobufSources),
    )
