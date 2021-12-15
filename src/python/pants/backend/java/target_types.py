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
from pants.jvm.target_types import (
    JunitTestSourceField,
    JvmCompatibleResolvesField,
    JvmProvidesTypesField,
    JvmResolveField,
)


class JavaSourceField(SingleSourceField):
    expected_file_extensions = (".java",)


class JavaGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = (".java",)


@dataclass(frozen=True)
class JavaFieldSet(FieldSet):
    required_fields = (JavaSourceField,)

    sources: JavaSourceField


@dataclass(frozen=True)
class JavaGeneratorFieldSet(FieldSet):
    required_fields = (JavaGeneratorSourcesField,)

    sources: JavaGeneratorSourcesField


# -----------------------------------------------------------------------------------------------
# `junit_test` and `junit_tests` targets
# -----------------------------------------------------------------------------------------------


class JavaJunitTestSourceField(JavaSourceField, JunitTestSourceField):
    """A JUnit test file written in Java."""


class JunitTestTarget(Target):
    alias = "junit_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaJunitTestSourceField,
        Dependencies,
        JvmResolveField,
        JvmProvidesTypesField,
    )
    help = "A single Java test, run with JUnit."


class JavaTestsGeneratorSourcesField(JavaGeneratorSourcesField):
    default = ("*Test.java",)


class JunitTestsGeneratorTarget(Target):
    alias = "junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaTestsGeneratorSourcesField,
        Dependencies,
        JvmResolveField,
        JvmProvidesTypesField,
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
        JvmCompatibleResolvesField,
        JvmProvidesTypesField,
    )
    help = "A single Java source file containing application or library code."


class JavaSourcesGeneratorSourcesField(JavaGeneratorSourcesField):
    default = ("*.java",) + tuple(f"!{pat}" for pat in JavaTestsGeneratorSourcesField.default)


class JavaSourcesGeneratorTarget(Target):
    alias = "java_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaSourcesGeneratorSourcesField,
        JvmCompatibleResolvesField,
        JvmProvidesTypesField,
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


class JvmMainClassNameField(StringField):
    alias = "main"
    required = True
    help = (
        "`.`-separated name of the JVM class containing the `main()` method to be called when "
        "executing this JAR."
    )


class DeployJarTarget(Target):
    alias = "deploy_jar"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        OutputPathField,
        JvmMainClassNameField,
        JvmResolveField,
    )
    help = (
        "A `jar` file with first and third-party code bundled for deploys.\n\n"
        "The JAR will contain class files for both first-party code and "
        "third-party dependencies, all in a common directory structure."
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromJunitTests),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromJavaSources),
    )
