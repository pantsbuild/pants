# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    GeneratedTargets,
    GenerateTargetsRequest,
    MultipleSourcesField,
    SingleSourceField,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    generate_file_level_targets,
)
from pants.engine.unions import UnionMembership, UnionRule


class WsdlDependenciesField(Dependencies):
    pass


# -----------------------------------------------------------------------------------------------
# `wsdl_source` target
# -----------------------------------------------------------------------------------------------


class WsdlSourceField(SingleSourceField):
    expected_file_extensions = (".wsdl",)


class WsdlSourceTarget(Target):
    alias = "wsdl_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        WsdlDependenciesField,
        WsdlSourceField,
    )
    help = "A single WSDL file used to generate various languages."


# -----------------------------------------------------------------------------------------------
# `wsdl_sources` target generator
# -----------------------------------------------------------------------------------------------


class WsdlSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.wsdl",)
    expected_file_extensions = (".wsdl",)


class WsdlSourcesGeneratorTarget(Target):
    alias = "wsdl_sources"
    core_fields = (*COMMON_TARGET_FIELDS, WsdlDependenciesField, WsdlSourcesGeneratingSourcesField)
    help = "Generate a `wsdl_source` target for each file in the `sources` field."


class GenerateTargetsFromWsdlSources(GenerateTargetsRequest):
    generate_from = WsdlSourcesGeneratorTarget


@rule
async def generate_targets_from_wsdl_sources(
    request: GenerateTargetsFromWsdlSources, union_memership: UnionMembership
) -> GeneratedTargets:
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[WsdlSourcesGeneratingSourcesField])
    )

    return generate_file_level_targets(
        WsdlSourceTarget,
        request.generator,
        sources_paths.files,
        union_memership,
        add_dependencies_on_all_siblings=False,
        use_source_field=True,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromWsdlSources),
    )
