# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
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


class ScalaSourceField(Sources):
    expected_file_extensions = (".scala",)
    expected_num_files = 1


class ScalaGeneratorSources(Sources):
    expected_file_extensions = (".scala",)


# -----------------------------------------------------------------------------------------------
# `junit_test` target
# -----------------------------------------------------------------------------------------------


class ScalaTestSourceField(ScalaSourceField):
    pass


class ScalaJunitTestTarget(Target):
    alias = "scala_junit_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ScalaTestSourceField,
    )
    help = "A single Scala test, run with JUnit."


# -----------------------------------------------------------------------------------------------
# `scala_junit_tests` target generator
# -----------------------------------------------------------------------------------------------


class ScalaTestsGeneratorSourcesField(ScalaGeneratorSources):
    default = ("*Test.scala",)


class ScalaJunitTestsGeneratorTarget(Target):
    alias = "scala_junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalaTestsGeneratorSourcesField,
        Dependencies,
    )
    help = (
        "Generate a `junit_test` target for each file in the `sources` field (defaults to "
        "all files in the directory that end in `Test.scala` )."
    )


class GenerateTargetsFromScalaJunitTests(GenerateTargetsRequest):
    generate_from = ScalaJunitTestsGeneratorTarget


@rule
async def generate_targets_from_scala_junit_tests(
    request: GenerateTargetsFromScalaJunitTests, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[ScalaTestsGeneratorSourcesField])
    )
    return generate_file_level_targets(
        ScalaJunitTestTarget,
        request.generator,
        paths.files,
        union_membership,
        add_dependencies_on_all_siblings=True,
    )


# -----------------------------------------------------------------------------------------------
# `scala_source` target
# -----------------------------------------------------------------------------------------------


class ScalaSourceTarget(Target):
    alias = "scala_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ScalaSourceField,
    )
    help = "A single Scala source file containing application or library code."


# -----------------------------------------------------------------------------------------------
# `scala_sources` target generator
# -----------------------------------------------------------------------------------------------


class ScalaSourcesGeneratorSourcesField(ScalaGeneratorSources):
    default = ("*.scala",) + tuple(f"!{pat}" for pat in ScalaTestsGeneratorSourcesField.default)


class ScalaSourcesGeneratorTarget(Target):
    alias = "scala_sources"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ScalaSourcesGeneratorSourcesField)
    help = (
        "Generate a `scala_source` target for each file in the `sources` field (defaults to "
        "all files named in the directory whose names end in `.scala` except for those which "
        "end in `Test.scala`)."
    )


class GenerateTargetsFromScalaSources(GenerateTargetsRequest):
    generate_from = ScalaSourcesGeneratorTarget


@rule
async def generate_targets_from_scala_sources(
    request: GenerateTargetsFromScalaSources, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[ScalaSourcesGeneratorSourcesField])
    )
    return generate_file_level_targets(
        ScalaSourceTarget,
        request.generator,
        paths.files,
        union_membership,
        add_dependencies_on_all_siblings=True,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromScalaJunitTests),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromScalaSources),
    )
