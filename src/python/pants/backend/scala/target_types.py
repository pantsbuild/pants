# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

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


class ScalaSourceField(SingleSourceField):
    expected_file_extensions = (".scala",)


class ScalaGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = (".scala",)


@dataclass(frozen=True)
class ScalaFieldSet(FieldSet):
    required_fields = (ScalaSourceField,)

    sources: ScalaSourceField


@dataclass(frozen=True)
class ScalaGeneratorFieldSet(FieldSet):
    required_fields = (ScalaGeneratorSourcesField,)

    sources: ScalaGeneratorSourcesField


# -----------------------------------------------------------------------------------------------
# `scalatest_tests`
# -----------------------------------------------------------------------------------------------


class ScalatestTestSourceField(ScalaSourceField):
    pass


class ScalatestTestTarget(Target):
    alias = "scalatest_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ScalatestTestSourceField,
        JvmResolveField,
        JvmProvidesTypesField,
    )
    help = "A single Scala test, run with Scalatest."


class ScalatestTestsGeneratorSourcesField(ScalaGeneratorSourcesField):
    default = ("*Spec.scala", "*Suite.scala")


class ScalatestTestsGeneratorTarget(Target):
    alias = "scalatest_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalatestTestsGeneratorSourcesField,
        Dependencies,
        JvmResolveField,
        JvmProvidesTypesField,
    )
    help = (
        "Generate a `scalatest_test` target for each file in the `sources` field (defaults to "
        f"all files in the directory matching {ScalatestTestsGeneratorSourcesField.default})."
    )


class GenerateTargetsFromScalatestTests(GenerateTargetsRequest):
    generate_from = ScalatestTestsGeneratorTarget


@rule
async def generate_targets_from_scala_scalatest_tests(
    request: GenerateTargetsFromScalatestTests, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[ScalatestTestsGeneratorSourcesField])
    )
    return generate_file_level_targets(
        ScalatestTestTarget,
        request.generator,
        paths.files,
        union_membership,
        add_dependencies_on_all_siblings=True,
        use_source_field=True,
    )


# -----------------------------------------------------------------------------------------------
# `scala_junit_tests`
# -----------------------------------------------------------------------------------------------


class ScalaJunitTestSourceField(ScalaSourceField, JunitTestSourceField):
    pass


class ScalaJunitTestTarget(Target):
    alias = "scala_junit_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ScalaJunitTestSourceField,
        JvmResolveField,
        JvmProvidesTypesField,
    )
    help = "A single Scala test, run with JUnit."


class ScalaJunitTestsGeneratorSourcesField(ScalaGeneratorSourcesField):
    default = ("*Test.scala",)


class ScalaJunitTestsGeneratorTarget(Target):
    alias = "scala_junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalaJunitTestsGeneratorSourcesField,
        Dependencies,
        JvmResolveField,
        JvmProvidesTypesField,
    )
    help = "Generate a `scala_junit_test` target for each file in the `sources` field."


class GenerateTargetsFromScalaJunitTests(GenerateTargetsRequest):
    generate_from = ScalaJunitTestsGeneratorTarget


@rule
async def generate_targets_from_scala_junit_tests(
    request: GenerateTargetsFromScalaJunitTests, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[ScalaJunitTestsGeneratorSourcesField])
    )
    return generate_file_level_targets(
        ScalaJunitTestTarget,
        request.generator,
        paths.files,
        union_membership,
        add_dependencies_on_all_siblings=True,
        use_source_field=True,
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
        JvmCompatibleResolvesField,
        JvmProvidesTypesField,
    )
    help = "A single Scala source file containing application or library code."


# -----------------------------------------------------------------------------------------------
# `scala_sources` target generator
# -----------------------------------------------------------------------------------------------


class ScalaSourcesGeneratorSourcesField(ScalaGeneratorSourcesField):
    default = tuple(
        (
            "*.scala",
            *(f"!{pat}" for pat in (ScalaJunitTestsGeneratorSourcesField.default)),
            *(f"!{pat}" for pat in (ScalatestTestsGeneratorSourcesField.default)),
        )
    )


class ScalaSourcesGeneratorTarget(Target):
    alias = "scala_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ScalaSourcesGeneratorSourcesField,
        JvmCompatibleResolvesField,
        JvmProvidesTypesField,
    )
    help = "Generate a `scala_source` target for each file in the `sources` field."


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
        use_source_field=True,
    )


# -----------------------------------------------------------------------------------------------
# `scalac_plugin` target
# -----------------------------------------------------------------------------------------------


class ScalacPluginArtifactField(StringField):
    alias = "artifact"
    required = True
    help = "The address of a `jvm_artifact` that defines a plugin for `scalac`."


class ScalacPluginNameField(StringField):
    alias = "plugin_name"
    help = (
        "The name that `scalac` should use to load the plugin.\n\n"
        "If not set, the plugin name defaults to the target name."
    )


class ScalacPluginTarget(Target):
    alias = "scalac_plugin"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalacPluginArtifactField,
        ScalacPluginNameField,
    )
    help = (
        "A plugin for `scalac`.\n\n"
        "Currently only thirdparty plugins are supported. To enable a plugin, define this "
        "target type, and set the `artifact=` field to the address of a `jvm_artifact` that "
        "provides the plugin.\n\n"
        "If the `scalac`-loaded name of the plugin does not match the target's name, "
        "additionally set the `plugin_name=` field."
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromScalaJunitTests),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromScalaSources),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromScalatestTests),
    )
