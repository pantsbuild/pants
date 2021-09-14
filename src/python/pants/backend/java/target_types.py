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


class GenerateJunitTestsFromJunitTests(GenerateTargetsRequest):
    target_class = JunitTests


@rule
async def generate_junit_tests_from_junit_tests(
    request: GenerateJunitTestsFromJunitTests, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(SourcesPaths, SourcesPathsRequest(request.target[JavaTestsSources]))
    return generate_file_level_targets(JunitTests, request.target, paths.files, union_membership)


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


class GenerateJavaLibraryFromJavaLibrary(GenerateTargetsRequest):
    target_class = JavaLibrary


@rule
async def generate_java_library_from_java_library(
    request: GenerateJavaLibraryFromJavaLibrary, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(SourcesPaths, SourcesPathsRequest(request.target[JavaLibrarySources]))
    return generate_file_level_targets(JavaLibrary, request.target, paths.files, union_membership)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateJunitTestsFromJunitTests),
        UnionRule(GenerateTargetsRequest, GenerateJavaLibraryFromJavaLibrary),
    )
