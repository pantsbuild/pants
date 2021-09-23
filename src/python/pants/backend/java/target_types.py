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


class JavaSourceField(Sources):
    expected_file_extensions = (".java",)
    expected_num_files = 1


class JavaGeneratorSources(Sources):
    expected_file_extensions = (".java",)


# -----------------------------------------------------------------------------------------------
# `junit_test` target
# -----------------------------------------------------------------------------------------------


class JavaTestSourceField(JavaSourceField):
    pass


class JunitTestTarget(Target):
    alias = "junit_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaTestSourceField,
    )
    help = "A single Java test, run with JUnit."


# -----------------------------------------------------------------------------------------------
# `junit_tests` target generator
# -----------------------------------------------------------------------------------------------


class JavaTestsGeneratorSourcesField(JavaGeneratorSources):
    default = ("*Test.java",)


class JunitTestsGeneratorTarget(Target):
    alias = "junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaTestsGeneratorSourcesField,
        Dependencies,
    )
    help = (
        "Generate a `junit_test` target for each file in the `sources` field (defaults to "
        "all files in the directory that end in `Test.java` )."
    )


class GenerateTargetsFromJunitTests(GenerateTargetsRequest):
    generate_from = JunitTestsGeneratorTarget


@rule
async def generate_targets_from_junit_tests(
    request: GenerateTargetsFromJunitTests, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[JavaTestsGeneratorSourcesField])
    )
    return generate_file_level_targets(
        JunitTestTarget,
        request.generator,
        paths.files,
        union_membership,
        # TODO(#12790): set to false when dependency inference is disabled.
        add_dependencies_on_all_siblings=True,
    )


# -----------------------------------------------------------------------------------------------
# `java_source` target
# -----------------------------------------------------------------------------------------------


class JavaSourceTarget(Target):
    alias = "java_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaSourceField,
    )
    help = "A single Java source file containing application or library code."


# -----------------------------------------------------------------------------------------------
# `java_sources` target generator
# -----------------------------------------------------------------------------------------------


class JavaSourcesGeneratorSourcesField(JavaGeneratorSources):
    default = ("*.java",) + tuple(f"!{pat}" for pat in JavaTestsGeneratorSourcesField.default)


class JavaSourcesGeneratorTarget(Target):
    alias = "java_sources"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, JavaSourcesGeneratorSourcesField)
    help = (
        "Generate a `java_source` target for each file in the `sources` field (defaults to "
        "all files named in the directory whose names end in `.java` except for those which "
        "end in `Test.java`)."
    )


class GenerateTargetsFromJavaSources(GenerateTargetsRequest):
    generate_from = JavaSourcesGeneratorTarget


@rule
async def generate_targets_from_java_sources(
    request: GenerateTargetsFromJavaSources, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[JavaSourcesGeneratorSourcesField])
    )
    return generate_file_level_targets(
        JavaSourceTarget,
        request.generator,
        paths.files,
        union_membership,
        # TODO(#12790): set to false when dependency inference is disabled.
        add_dependencies_on_all_siblings=True,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromJunitTests),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromJavaSources),
    )
