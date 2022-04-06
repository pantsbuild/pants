# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    StringField,
    StringSequenceField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.target_types import (
    JunitTestSourceField,
    JvmJdkField,
    JvmProvidesTypesField,
    JvmResolveField,
)


class ScalaSettingsRequest(TargetFilesGeneratorSettingsRequest):
    pass


@rule
def scala_settings_request(_: ScalaSettingsRequest) -> TargetFilesGeneratorSettings:
    # TODO: See https://github.com/pantsbuild/pants/issues/14382.
    return TargetFilesGeneratorSettings(add_dependencies_on_all_siblings=True)


class ScalaSourceField(SingleSourceField):
    expected_file_extensions = (".scala",)


class ScalaGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = (".scala",)


class ScalaDependenciesField(Dependencies):
    pass


class ScalaConsumedPluginNamesField(StringSequenceField):
    help = (
        "The names of Scala plugins that this source file requires.\n\n"
        "The plugin must be defined by a corresponding `scalac_plugin` AND `jvm_artifact` target, "
        "and must be present in this target's resolve's lockfile.\n\n"
        "If not specified, this will default to the plugins specified in "
        "`[scalac].plugins_for_resolve` for this target's resolve."
    )

    alias = "scalac_plugins"
    required = False


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
        ScalaDependenciesField,
        ScalatestTestSourceField,
        ScalaConsumedPluginNamesField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Scala test, run with Scalatest."


class ScalatestTestsGeneratorSourcesField(ScalaGeneratorSourcesField):
    default = ("*Spec.scala", "*Suite.scala")


class ScalatestTestsGeneratorTarget(TargetFilesGenerator):
    alias = "scalatest_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalatestTestsGeneratorSourcesField,
    )
    generated_target_cls = ScalatestTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        ScalaDependenciesField,
        ScalaConsumedPluginNamesField,
        JvmJdkField,
        JvmProvidesTypesField,
        JvmResolveField,
    )
    settings_request_cls = ScalaSettingsRequest
    help = (
        "Generate a `scalatest_test` target for each file in the `sources` field (defaults to "
        f"all files in the directory matching {ScalatestTestsGeneratorSourcesField.default})."
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
        ScalaDependenciesField,
        ScalaJunitTestSourceField,
        ScalaConsumedPluginNamesField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Scala test, run with JUnit."


class ScalaJunitTestsGeneratorSourcesField(ScalaGeneratorSourcesField):
    default = ("*Test.scala",)


class ScalaJunitTestsGeneratorTarget(TargetFilesGenerator):
    alias = "scala_junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalaJunitTestsGeneratorSourcesField,
    )
    generated_target_cls = ScalaJunitTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        ScalaDependenciesField,
        ScalaConsumedPluginNamesField,
        JvmJdkField,
        JvmProvidesTypesField,
        JvmResolveField,
    )
    settings_request_cls = ScalaSettingsRequest
    help = "Generate a `scala_junit_test` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `scala_source` target
# -----------------------------------------------------------------------------------------------


class ScalaSourceTarget(Target):
    alias = "scala_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalaDependenciesField,
        ScalaSourceField,
        ScalaConsumedPluginNamesField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Scala source file containing application or library code."


# -----------------------------------------------------------------------------------------------
# `scala_sources` target generator
# -----------------------------------------------------------------------------------------------


class ScalaSourcesGeneratorSourcesField(ScalaGeneratorSourcesField):
    default = (
        "*.scala",
        *(f"!{pat}" for pat in (ScalaJunitTestsGeneratorSourcesField.default)),
        *(f"!{pat}" for pat in (ScalatestTestsGeneratorSourcesField.default)),
    )


class ScalaSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "scala_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalaSourcesGeneratorSourcesField,
    )
    generated_target_cls = ScalaSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        ScalaDependenciesField,
        ScalaConsumedPluginNamesField,
        JvmResolveField,
        JvmJdkField,
        JvmProvidesTypesField,
    )
    settings_request_cls = ScalaSettingsRequest
    help = "Generate a `scala_source` target for each file in the `sources` field."


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
        UnionRule(TargetFilesGeneratorSettingsRequest, ScalaSettingsRequest),
    )
