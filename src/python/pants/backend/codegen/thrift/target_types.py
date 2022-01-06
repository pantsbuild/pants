# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.subsystem import ThriftSubsystem
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
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
# `thrift_source` targets.
class ThriftDependenciesField(Dependencies):
    pass


class AllThriftTargets(Targets):
    pass


@rule(desc="Find all Thrift targets in project", level=LogLevel.DEBUG)
def find_all_thrift_targets(targets: AllTargets) -> AllThriftTargets:
    return AllThriftTargets(tgt for tgt in targets if tgt.has_field(ThriftSourceField))


# -----------------------------------------------------------------------------------------------
# `thrift_source` target
# -----------------------------------------------------------------------------------------------


class ThriftSourceField(SingleSourceField):
    expected_file_extensions = (".thrift",)


class ThriftSourceTarget(Target):
    alias = "thrift_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ThriftDependenciesField,
        ThriftSourceField,
    )
    help = (
        "A single Thrift file used to generate various languages.\n\n" f"See {doc_url('thrift')}."
    )


# -----------------------------------------------------------------------------------------------
# `thrift_sources` target generator
# -----------------------------------------------------------------------------------------------


class ThriftSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.thrift",)
    expected_file_extensions = (".thrift",)


class ThriftSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        ThriftSourceTarget.alias,
        (
            "overrides={\n"
            '  "bar.thrift": {"description": "our user model"]},\n'
            '  ("foo.thrift", "bar.thrift"): {"tags": ["overridden"]},\n'
            "}"
        ),
    )


class ThriftSourcesGeneratorTarget(Target):
    alias = "thrift_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ThriftDependenciesField,
        ThriftSourcesGeneratingSourcesField,
        ThriftSourcesOverridesField,
    )
    help = "Generate a `thrift_source` target for each file in the `sources` field."


class GenerateTargetsFromThriftSources(GenerateTargetsRequest):
    generate_from = ThriftSourcesGeneratorTarget


@rule
async def generate_targets_from_thrift_sources(
    request: GenerateTargetsFromThriftSources,
    files_not_found_behavior: FilesNotFoundBehavior,
    thrift: ThriftSubsystem,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[ThriftSourcesGeneratingSourcesField])
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
        ThriftSourceTarget,
        request.generator,
        sources_paths.files,
        union_membership,
        add_dependencies_on_all_siblings=not thrift.dependency_inference,
        overrides=all_overrides,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromThriftSources),
    )
