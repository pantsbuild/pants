# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.rules import collect_rules
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
)
from pants.jvm.target_types import JvmJdkField, JvmProvidesTypesField, JvmResolveField
from pants.util.strutil import softwrap


class KotlinSourceField(SingleSourceField):
    expected_file_extensions = (".kt",)


class KotlinGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = (".kt",)


class KotlincConsumedPluginIdsField(StringSequenceField):
    help = softwrap(
        """
        The IDs of Kotlin compiler plugins that this source file requires.

        The plugin must be defined by a corresponding `kotlinc_plugin` AND `jvm_artifact` target,
        and must be present in this target's resolve's lockfile.

        If not specified, this will default to the plugins specified in
        `[kotlinc].plugins_for_resolve` for this target's resolve.
        """
    )

    alias = "kotlinc_plugins"
    required = False


@dataclass(frozen=True)
class KotlinFieldSet(FieldSet):
    required_fields = (KotlinSourceField,)

    sources: KotlinSourceField


@dataclass(frozen=True)
class KotlinGeneratorFieldSet(FieldSet):
    required_fields = (KotlinGeneratorSourcesField,)

    sources: KotlinGeneratorSourcesField


class KotlinDependenciesField(Dependencies):
    pass


# -----------------------------------------------------------------------------------------------
# `kotlin_source` and `kotlin_sources` targets
# -----------------------------------------------------------------------------------------------


class KotlinSourceTarget(Target):
    alias = "kotlin_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        KotlinDependenciesField,
        KotlinSourceField,
        KotlincConsumedPluginIdsField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Kotlin source file containing application or library code."


class KotlinSourcesGeneratorSourcesField(KotlinGeneratorSourcesField):
    default = ("*.kt",)


class KotlinSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "kotlin_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        KotlinSourcesGeneratorSourcesField,
    )
    generated_target_cls = KotlinSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        KotlinDependenciesField,
        KotlincConsumedPluginIdsField,
        JvmResolveField,
        JvmJdkField,
        JvmProvidesTypesField,
    )
    help = "Generate a `kotlin_source` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `kotlinc_plugin` target type
# -----------------------------------------------------------------------------------------------


class KotlincPluginArtifactField(StringField):
    alias = "artifact"
    required = True
    help = "The address of a `jvm_artifact` that defines a plugin for `kotlinc`."


class KotlincPluginIdField(StringField):
    alias = "plugin_id"
    help = softwrap(
        """
        The ID for `kotlinc` to use when setting options for the plugin.

        If not set, the plugin ID defaults to the target name.
        """
    )


class KotlincPluginArgsField(StringSequenceField):
    alias = "plugin_args"
    help = softwrap(
        """
        Optional list of argument to pass to the plugin.
        """
    )


class KotlincPluginTarget(Target):
    alias = "kotlinc_plugin"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        KotlincPluginArtifactField,
        KotlincPluginIdField,
        KotlincPluginArgsField,
    )
    help = softwrap(
        """
        A plugin for `kotlinc`.

        To enable a `kotlinc` plugin, define a target with this target type, and set the `artifact` field to the
        address of a `jvm_artifact` target that provides the plugin. Set the `plugin_id` field to the ID of the
        plugin if that name cannot be inferred from the `name` of this target.

        The standard `kotlinc` plugins are available via the following artifact coordinates and IDs:
        * All-open: `org.jetbrains.kotlin:kotlin-allopen:VERSION` (ID: `all-open`)
        * No-arg: `org.jetbrains.kotlin:kotlin-noarg:VERSION` (ID: `no-arg`)
        * SAM with receiver: `org.jetbrains.kotlin:kotlin-sam-with-receiver:VERSION` (ID: `sam-with-receiver`)
        * kapt (annotation processor): `org.jetbrains.kotlin:org.jetbrains.kotlin:kotlin-annotation-processing-embeddable:VERSION` (ID: `kapt3`)
        * Seralization: `org.jetbrains.kotlin:kotlin-serialization:VERSION` (ID: `serialization`)
        """
    )


def rules():
    return collect_rules()
