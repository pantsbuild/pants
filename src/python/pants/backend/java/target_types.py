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


class JavaSources(Sources):
    expected_file_extensions = (".java",)


# -----------------------------------------------------------------------------------------------
# `java_tests` target
# -----------------------------------------------------------------------------------------------


class JavaTestsSources(JavaSources):
    default = ("*Test.java",)


class JunitTests(Target):
    alias = "junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaTestsSources,
    )
    help = "Java tests, run with Junit."


class GenerateTargetsFromJunitTests(GenerateTargetsRequest):
    generate_from = JunitTests


@rule
async def generate_targets_from_junit_tests(
    request: GenerateTargetsFromJunitTests, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(SourcesPaths, SourcesPathsRequest(request.generator[JavaTestsSources]))
    return generate_file_level_targets(
        JunitTests,
        request.generator,
        paths.files,
        union_membership,
        # TODO(#12790): set to false when dependency inference is disabled.
        add_dependencies_on_all_siblings=True,
    )


# -----------------------------------------------------------------------------------------------
# `java_library` target
# -----------------------------------------------------------------------------------------------


class JavaLibrarySources(JavaSources):
    default = ("*.java",) + tuple(f"!{pat}" for pat in JavaTestsSources.default)


class JavaLibrary(Target):
    alias = "java_library"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaLibrarySources,
    )
    help = "Java source code."


class GenerateTargetsFromJavaLibrary(GenerateTargetsRequest):
    generate_from = JavaLibrary


@rule
async def generate_targets_from_java_library(
    request: GenerateTargetsFromJavaLibrary, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(SourcesPaths, SourcesPathsRequest(request.generator[JavaLibrarySources]))
    return generate_file_level_targets(
        JavaLibrary,
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
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromJavaLibrary),
    )
