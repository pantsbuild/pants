# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scala_infer import ScalaInferSubsystem
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals.test import TestExtraEnvVarsField, TestTimeoutField
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    Dependencies,
    FieldSet,
    GeneratedTargets,
    GenerateTargetsRequest,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    StringField,
    StringSequenceField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
    TargetGenerator,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm import target_types as jvm_target_types
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import (
    JunitTestExtraEnvVarsField,
    JunitTestSourceField,
    JunitTestTimeoutField,
    JvmArtifactArtifactField,
    JvmArtifactExclusion,
    JvmArtifactExclusionsField,
    JvmArtifactGroupField,
    JvmArtifactJarSourceField,
    JvmArtifactPackagesField,
    JvmArtifactResolveField,
    JvmArtifactTarget,
    JvmArtifactUrlField,
    JvmArtifactVersionField,
    JvmJdkField,
    JvmMainClassNameField,
    JvmProvidesTypesField,
    JvmResolveField,
    JvmRunnableSourceFieldSet,
    _jvm_artifact_exclusions_field_help,
)
from pants.util.strutil import help_text, softwrap


class ScalaSettingsRequest(TargetFilesGeneratorSettingsRequest):
    pass


@rule
def scala_settings_request(
    scala_infer_subsystem: ScalaInferSubsystem, _: ScalaSettingsRequest
) -> TargetFilesGeneratorSettings:
    return TargetFilesGeneratorSettings(
        add_dependencies_on_all_siblings=scala_infer_subsystem.force_add_siblings_as_dependencies
        or not scala_infer_subsystem.imports
    )


class ScalaSourceField(SingleSourceField):
    expected_file_extensions = (".scala",)


class ScalaGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = (".scala",)


class ScalaDependenciesField(Dependencies):
    pass


class ScalaConsumedPluginNamesField(StringSequenceField):
    help = help_text(
        """
        The names of Scala plugins that this source file requires.

        The plugin must be defined by a corresponding `scalac_plugin` AND `jvm_artifact` target,
        and must be present in this target's resolve's lockfile.

        If not specified, this will default to the plugins specified in
        `[scalac].plugins_for_resolve` for this target's resolve.
        """
    )

    alias = "scalac_plugins"
    required = False


@dataclass(frozen=True)
class ScalaFieldSet(JvmRunnableSourceFieldSet):
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


class ScalatestTestTimeoutField(TestTimeoutField):
    pass


class ScalatestTestExtraEnvVarsField(TestExtraEnvVarsField):
    pass


class ScalatestTestTarget(Target):
    alias = "scalatest_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalaDependenciesField,
        ScalatestTestSourceField,
        ScalaConsumedPluginNamesField,
        ScalatestTestTimeoutField,
        ScalatestTestExtraEnvVarsField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Scala test, run with Scalatest."


class ScalatestTestsGeneratorSourcesField(ScalaGeneratorSourcesField):
    default = ("*Spec.scala", "*Suite.scala")
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['*Spec.scala', '!SuiteIgnore.scala']`"
    )


class ScalatestTestsSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        "scalatest_tests",
        """
        overrides={
            "Foo.scala": {"dependencies": [":files"]},
            "Bar.scala": {"skip_scalafmt": True},
            ("Foo.scala", "Bar.scala"): {"tags": ["linter_disabled"]},
        }"
        """,
    )


class ScalatestTestsGeneratorTarget(TargetFilesGenerator):
    alias = "scalatest_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalatestTestsGeneratorSourcesField,
        ScalatestTestsSourcesOverridesField,
    )
    generated_target_cls = ScalatestTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        ScalaDependenciesField,
        ScalaConsumedPluginNamesField,
        ScalatestTestTimeoutField,
        ScalatestTestExtraEnvVarsField,
        JvmJdkField,
        JvmProvidesTypesField,
        JvmResolveField,
    )
    settings_request_cls = ScalaSettingsRequest
    help = help_text(
        f"""
        Generate a `scalatest_test` target for each file in the `sources` field (defaults to
        all files in the directory matching {ScalatestTestsGeneratorSourcesField.default}).
        """
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
        JunitTestTimeoutField,
        JunitTestExtraEnvVarsField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Scala test, run with JUnit."


class ScalaJunitTestsGeneratorSourcesField(ScalaGeneratorSourcesField):
    default = ("*Test.scala",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['*Test.scala', '!TestIgnore.scala']`"
    )


class ScalaJunitTestsSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        "scala_junit_tests",
        """
        overrides={
            "Foo.scala": {"dependencies": [":files"]},
            "Bar.scala": {"skip_scalafmt": True},
            ("Foo.scala", "Bar.scala"): {"tags": ["linter_disabled"]},
        }"
        """,
    )


class ScalaJunitTestsGeneratorTarget(TargetFilesGenerator):
    alias = "scala_junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalaJunitTestsGeneratorSourcesField,
        ScalaJunitTestsSourcesOverridesField,
        JunitTestTimeoutField,
    )
    generated_target_cls = ScalaJunitTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        ScalaDependenciesField,
        ScalaConsumedPluginNamesField,
        JunitTestTimeoutField,
        JunitTestExtraEnvVarsField,
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
        JvmMainClassNameField,
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
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['Example.scala', 'New*.scala', '!OldIgnore.scala']`"
    )


class ScalaSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        "scala_sources",
        """
        overrides={
            "Foo.scala": {"dependencies": [":files"]},
            "Bar.scala": {"skip_scalafmt": True},
            ("Foo.scala", "Bar.scala"): {"tags": ["linter_disabled"]},
        }"
        """,
    )


class ScalaSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "scala_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalaSourcesGeneratorSourcesField,
        ScalaSourcesOverridesField,
    )
    generated_target_cls = ScalaSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        ScalaDependenciesField,
        ScalaConsumedPluginNamesField,
        JvmResolveField,
        JvmJdkField,
        JvmMainClassNameField,
        JvmProvidesTypesField,
    )
    settings_request_cls = ScalaSettingsRequest
    help = "Generate a `scala_source` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `scalac_plugin` target
# -----------------------------------------------------------------------------------------------


class ScalacPluginArtifactField(StringField, AsyncFieldMixin):
    alias = "artifact"
    required = True
    value: str
    help = "The address of either a `jvm_artifact` or a `scala_artifact` that defines a plugin for `scalac`."


class ScalacPluginNameField(StringField):
    alias = "plugin_name"
    help = help_text(
        """
        The name that `scalac` should use to load the plugin.

        If not set, the plugin name defaults to the target name.
        """
    )


class ScalacPluginTarget(Target):
    alias = "scalac_plugin"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ScalacPluginArtifactField,
        ScalacPluginNameField,
    )
    help = help_text(
        """
        A plugin for `scalac`.

        Currently only thirdparty plugins are supported. To enable a plugin, define this
        target type, and set the `artifact=` field to the address of a `jvm_artifact` that
        provides the plugin.

        If the `scalac`-loaded name of the plugin does not match the target's name,
        additionally set the `plugin_name=` field.
        """
    )


# -----------------------------------------------------------------------------------------------
# `scala_artifact` target
# -----------------------------------------------------------------------------------------------


class ScalaCrossVersion(Enum):
    PARTIAL = "partial"
    FULL = "full"


class ScalaArtifactCrossversionField(StringField):
    alias = "crossversion"
    default = ScalaCrossVersion.PARTIAL.value
    help = help_text(
        """
        Whether to use the full Scala version or the partial one to determine the artifact name suffix.

        Default is `partial`.
        """
    )
    valid_choices = ScalaCrossVersion


@dataclass(frozen=True)
class ScalaArtifactExclusion(JvmArtifactExclusion):
    alias = "scala_exclude"
    help = help_text(
        """
        Exclude the given `artifact` and `group`, or all artifacts from the given `group`.
        You can also use the `crossversion` field to help resolve the final artifact name.
        """
    )

    crossversion: str = ScalaCrossVersion.PARTIAL.value

    def validate(self) -> set[str]:
        errors = super().validate()
        valid_crossversions = [x.value for x in ScalaCrossVersion]
        if self.crossversion not in valid_crossversions:
            errors.add(
                softwrap(
                    f"""
                    Invalid `crossversion` value: {self.crossversion}. Valid values are:
                    {', '.join(valid_crossversions)}
                    """
                )
            )
        return errors


class ScalaArtifactExclusionsField(JvmArtifactExclusionsField):
    help = _jvm_artifact_exclusions_field_help(
        lambda: ScalaArtifactExclusionsField.supported_rule_types
    )
    supported_rule_types: ClassVar[tuple[type[JvmArtifactExclusion], ...]] = (
        JvmArtifactExclusion,
        ScalaArtifactExclusion,
    )


@dataclass(frozen=True)
class ScalaArtifactFieldSet(FieldSet):
    group: JvmArtifactGroupField
    artifact: JvmArtifactArtifactField
    version: JvmArtifactVersionField
    packages: JvmArtifactPackagesField
    exclusions: ScalaArtifactExclusionsField
    crossversion: ScalaArtifactCrossversionField

    required_fields = (
        JvmArtifactGroupField,
        JvmArtifactArtifactField,
        JvmArtifactVersionField,
        JvmArtifactPackagesField,
        ScalaArtifactCrossversionField,
    )


class ScalaArtifactTarget(TargetGenerator):
    alias = "scala_artifact"
    help = help_text(
        """
        A third-party Scala artifact, as identified by its Maven-compatible coordinate.

        That is, an artifact identified by its `group`, `artifact`, and `version` components.

        Each artifact is associated with one or more resolves (a logical name you give to a
        lockfile). For this artifact to be used by your first-party code, it must be
        associated with the resolve(s) used by that code. See the `resolve` field.

        Being a Scala artifact, the final artifact name will be inferred using the Scala version
        configured for the given resolve.
        """
    )
    core_fields = (
        *COMMON_TARGET_FIELDS,
        *ScalaArtifactFieldSet.required_fields,
        ScalaArtifactExclusionsField,
        JvmArtifactUrlField,
        JvmArtifactJarSourceField,
        JvmMainClassNameField,
    )
    copied_fields = (
        *COMMON_TARGET_FIELDS,
        JvmArtifactGroupField,
        JvmArtifactVersionField,
        JvmArtifactPackagesField,
        JvmArtifactUrlField,
        JvmArtifactJarSourceField,
        JvmMainClassNameField,
    )
    moved_fields = (
        JvmArtifactResolveField,
        JvmJdkField,
    )


class GenerateJvmArtifactForScalaTargets(GenerateTargetsRequest):
    generate_from = ScalaArtifactTarget


@rule
async def generate_jvm_artifact_targets(
    request: GenerateJvmArtifactForScalaTargets,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    field_set = ScalaArtifactFieldSet.create(request.generator)
    resolve_name = request.template.get(JvmArtifactResolveField.alias) or jvm.default_resolve
    scala_version = scala.version_for_resolve(resolve_name)
    scala_version_parts = scala_version.split(".")

    def scala_suffix(crossversion: ScalaCrossVersion) -> str:
        if crossversion == ScalaCrossVersion.FULL:
            return scala_version
        elif int(scala_version_parts[0]) >= 3:
            return scala_version_parts[0]

        return f"{scala_version_parts[0]}.{scala_version_parts[1]}"

    exclusions_field = {}
    if field_set.exclusions.value:
        exclusions = []
        for exclusion in field_set.exclusions.value:
            if not isinstance(exclusion, ScalaArtifactExclusion):
                exclusions.append(exclusion)
            else:
                excluded_artifact_name = None
                if exclusion.artifact:
                    crossversion = ScalaCrossVersion(exclusion.crossversion)
                    excluded_artifact_name = f"{exclusion.artifact}_{scala_suffix(crossversion)}"
                exclusions.append(
                    JvmArtifactExclusion(group=exclusion.group, artifact=excluded_artifact_name)
                )
        exclusions_field[JvmArtifactExclusionsField.alias] = exclusions

    crossversion = ScalaCrossVersion(field_set.crossversion.value)
    artifact_name = f"{field_set.artifact.value}_{scala_suffix(crossversion)}"
    jvm_artifact_target = JvmArtifactTarget(
        {
            **request.template,
            JvmArtifactArtifactField.alias: artifact_name,
            **exclusions_field,
        },
        request.generator.address.create_generated(artifact_name),
        union_membership,
        residence_dir=request.generator.address.spec_path,
    )

    return GeneratedTargets(request.generator, (jvm_artifact_target,))


def rules():
    return (
        *collect_rules(),
        *jvm_target_types.rules(),
        *ScalaFieldSet.jvm_rules(),
        UnionRule(TargetFilesGeneratorSettingsRequest, ScalaSettingsRequest),
        UnionRule(GenerateTargetsRequest, GenerateJvmArtifactForScalaTargets),
    )


def build_file_aliases():
    return BuildFileAliases(objects={ScalaArtifactExclusion.alias: ScalaArtifactExclusion})
