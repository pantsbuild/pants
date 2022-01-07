# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
# `avro_source` targets.
class AvroDependenciesField(Dependencies):
    pass


class AllAvroTargets(Targets):
    pass


@rule(desc="Find all Avro targets in project", level=LogLevel.DEBUG)
def find_all_avro_targets(targets: AllTargets) -> AllAvroTargets:
    return AllAvroTargets(tgt for tgt in targets if tgt.has_field(AvroSourceField))


# -----------------------------------------------------------------------------------------------
# `avro_source` target
# -----------------------------------------------------------------------------------------------


class AvroSourceField(SingleSourceField):
    expected_file_extensions = (".avsc", ".avpr", ".avdl")


class AvroSourceTarget(Target):
    alias = "avro_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        AvroDependenciesField,
        AvroSourceField,
    )
    help = f"A single Avro file used to generate various languages.\n\nSee {doc_url('avro')}."


# -----------------------------------------------------------------------------------------------
# `avro_sources` target generator
# -----------------------------------------------------------------------------------------------


class AvroSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.avsc", "*.avpr", "*.avdl")
    expected_file_extensions = (".avsc", ".avpr", ".avdl")


class AvroSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        AvroSourceTarget.alias,
        (
            "overrides={\n"
            '  "bar.proto": {"description": "our user model"]},\n'
            '  ("foo.proto", "bar.proto"): {"tags": ["overridden"]},\n'
            "}"
        ),
    )


class AvroSourcesGeneratorTarget(Target):
    alias = "avro_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        AvroDependenciesField,
        AvroSourcesGeneratingSourcesField,
        AvroSourcesOverridesField,
    )
    help = "Generate a `avro_source` target for each file in the `sources` field."


class GenerateTargetsFromAvroSources(GenerateTargetsRequest):
    generate_from = AvroSourcesGeneratorTarget


@rule
async def generate_targets_from_avro_sources(
    request: GenerateTargetsFromAvroSources,
    files_not_found_behavior: FilesNotFoundBehavior,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[AvroSourcesGeneratingSourcesField])
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
        AvroSourceTarget,
        request.generator,
        sources_paths.files,
        union_membership,
        # Note: Avro files cannot import from other Avro files, so do not add dependencies.
        add_dependencies_on_all_siblings=False,
        overrides=all_overrides,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromAvroSources),
    )
