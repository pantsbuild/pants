# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.core.goals.package import OutputPathField
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    FieldSet,
    GeneratedTargets,
    GenerateTargetsRequest,
    MultipleSourcesField,
    SingleSourceField,
    SourcesPaths,
    SourcesPathsRequest,
    StringField,
    Target,
    generate_file_level_targets,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.target_types import JvmCompatibleResolveNamesField, JvmResolveName


class JavaSourceField(SingleSourceField):
    expected_file_extensions = (".java",)


class JavaGeneratorSources(MultipleSourcesField):
    expected_file_extensions = (".java",)


@dataclass(frozen=True)
class JavaFieldSet(FieldSet):
    required_fields = (JavaSourceField,)

    sources: JavaSourceField


@dataclass(frozen=True)
class JavaGeneratorFieldSet(FieldSet):
    required_fields = (JavaGeneratorSources,)

    sources: JavaGeneratorSources


# -----------------------------------------------------------------------------------------------
# `junit_test` and `junit_tests` targets
# -----------------------------------------------------------------------------------------------


class JavaTestSourceField(JavaSourceField):
    pass


class JunitTestTarget(Target):
    alias = "junit_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaTestSourceField,
        Dependencies,
        JvmCompatibleResolveNamesField,
    )
    help = "A single Java test, run with JUnit."


class JavaTestsGeneratorSourcesField(JavaGeneratorSources):
    default = ("*Test.java",)


class JunitTestsGeneratorTarget(Target):
    alias = "junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaTestsGeneratorSourcesField,
        Dependencies,
        JvmCompatibleResolveNamesField,
    )
    help = "Generate a `junit_test` target for each file in the `sources` field."


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
        add_dependencies_on_all_siblings=False,
    )


# -----------------------------------------------------------------------------------------------
# `java_source` and `java_sources` targets
# -----------------------------------------------------------------------------------------------


class JavaSourceTarget(Target):
    alias = "java_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaSourceField,
        JvmCompatibleResolveNamesField,
    )
    help = "A single Java source file containing application or library code."


class JavaSourcesGeneratorSourcesField(JavaGeneratorSources):
    default = ("*.java",) + tuple(f"!{pat}" for pat in JavaTestsGeneratorSourcesField.default)


class JavaSourcesGeneratorTarget(Target):
    alias = "java_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaSourcesGeneratorSourcesField,
        JvmCompatibleResolveNamesField,
    )
    help = "Generate a `java_source` target for each file in the `sources` field."


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
        add_dependencies_on_all_siblings=False,
        use_source_field=True,
    )


# Things for JARs
#


class JvmMainClassName(StringField):
    alias = "main"
    required = True
    help = (
        "`.`-separated name of the JVM class containing the `main()` method to be called when "
        "executing this JAR."
    )


class DeployJar(Target):
    alias = "deploy_jar"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        OutputPathField,
        JvmMainClassName,
        JvmResolveName,
    )
    help = (
        "A `jar` file that contains the compiled source code along with its dependency class "
        "files, where the compiled class files from all dependency JARs, along with first-party "
        "class files, exist in a common directory structure."
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromJunitTests),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromJavaSources),
    )
