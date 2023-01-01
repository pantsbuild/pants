# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.helm.resolve.remotes import ALL_DEFAULT_HELM_REGISTRIES
from pants.core.goals.package import OutputPathField
from pants.core.goals.test import TestTimeoutField
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    BoolField,
    Dependencies,
    DescriptionField,
    DictStringToStringField,
    FieldSet,
    IntField,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    Target,
    TargetFilesGenerator,
    Targets,
    TriBoolField,
    ValidNumbers,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.util.docutil import bin_name
from pants.util.strutil import softwrap
from pants.util.value_interpolation import InterpolationContext, InterpolationError

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Generic commonly used fields
# -----------------------------------------------------------------------------------------------


class HelmRegistriesField(StringSequenceField):
    alias = "registries"
    default = (ALL_DEFAULT_HELM_REGISTRIES,)
    help = softwrap(
        """
        List of addresses or configured aliases to any OCI registries to use for the
        built chart.

        The address is an `oci://` prefixed domain name with optional port for your registry, and any registry
        aliases are prefixed with `@` for addresses in the [helm].registries configuration
        section.

        By default, all configured registries with `default = true` are used.

        Example:

            # pants.toml
            [helm.registries.my-registry-alias]
            address = "oci://myregistrydomain:port"
            default = false  # optional

            # example/BUILD
            helm_chart(
                registries = [
                    "@my-registry-alias",
                    "oci://myregistrydomain:port",
                ],
            )

        The above example shows two valid `registry` options: using an alias to a configured
        registry and the address to a registry verbatim in the BUILD file.
        """
    )


class HelmSkipLintField(BoolField):
    alias = "skip_lint"
    default = False
    help = softwrap(
        f"""
        If set to true, do not run any linting in this Helm chart when running `{bin_name()}
        lint`.
        """
    )


class HelmSkipPushField(BoolField):
    alias = "skip_push"
    default = False
    help = softwrap(
        f"""
        If set to true, do not push this Helm chart to registries when running `{bin_name()}
        publish`.
        """
    )


# -----------------------------------------------------------------------------------------------
# `helm_chart` target
# -----------------------------------------------------------------------------------------------


class HelmChartMetaSourceField(SingleSourceField):
    alias = "chart"
    default = "Chart.yaml"
    expected_file_extensions = (
        ".yaml",
        ".yml",
    )
    required = False
    help = "The chart definition file."


class HelmChartSourcesField(MultipleSourcesField):
    default = (
        "values.yaml",
        "values.yml",
        "templates/*.yaml",
        "templates/*.yml",
        "templates/*.tpl",
        "crds/*.yaml",
        "crds/*.yml",
    )
    expected_file_extensions = (".yaml", ".yml", ".tpl")
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['values.yaml', 'templates/*.yaml', '!values_ignore.yaml']`"
    )


class HelmChartDependenciesField(Dependencies):
    pass


class HelmChartOutputPathField(OutputPathField):
    help = softwrap(
        f"""
        Where the built directory tree should be located.

        If undefined, this will use the path to the BUILD file,
        For example, `src/charts/mychart:tgt_name` would be
        `src.charts.mychart/tgt_name/`.

        Regardless of whether you use the default or set this field, the path will end with
        Helms's file format of `<chart_name>-<chart_version>.tgz`, where
        `chart_name` and `chart_version` are the values extracted from the Chart.yaml file.
        So, using the default for this field, the target
        `src/charts/mychart:tgt_name` might have a final path like
        `src.charts.mychart/tgt_name/mychart-0.1.0.tgz`.

        When running `{bin_name()} package`, this path will be prefixed by `--distdir` (e.g. `dist/`).

        Warning: setting this value risks naming collisions with other package targets you may
        have.
        """
    )


class HelmChartLintStrictField(TriBoolField):
    alias = "lint_strict"
    help = "If set to true, enables strict linting of this Helm chart."


class HelmChartRepositoryField(StringField):
    alias = "repository"
    help = softwrap(
        """
        Repository to use in the Helm registry where this chart is going to be published.

        If no value is given and `[helm].default-registry-repository` is undefined too, then the chart
        will be pushed to the root of the OCI registry.
        """
    )


class HelmChartTarget(Target):
    alias = "helm_chart"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmChartMetaSourceField,
        HelmChartSourcesField,
        HelmChartDependenciesField,
        HelmChartOutputPathField,
        HelmChartLintStrictField,
        HelmChartRepositoryField,
        HelmRegistriesField,
        HelmSkipPushField,
        HelmSkipLintField,
    )
    help = "A Helm chart."


@dataclass(frozen=True)
class HelmChartFieldSet(FieldSet):
    required_fields = (
        HelmChartMetaSourceField,
        HelmChartSourcesField,
    )

    chart: HelmChartMetaSourceField
    sources: HelmChartSourcesField
    dependencies: HelmChartDependenciesField


class AllHelmChartTargets(Targets):
    pass


@rule
def all_helm_chart_targets(all_targets: AllTargets) -> AllHelmChartTargets:
    return AllHelmChartTargets([tgt for tgt in all_targets if HelmChartFieldSet.is_applicable(tgt)])


# -----------------------------------------------------------------------------------------------
# `helm_unittest_test` target
# -----------------------------------------------------------------------------------------------


class HelmUnitTestDependenciesField(Dependencies):
    pass


class HelmUnitTestTimeoutField(TestTimeoutField):
    pass


class HelmUnitTestSourceField(SingleSourceField):
    expected_file_extensions = (
        ".yaml",
        ".yml",
    )


class HelmUnitTestStrictField(TriBoolField):
    alias = "strict"
    help = "If set to true, parses the UnitTest suite files strictly."


class HelmUnitTestTestTarget(Target):
    alias = "helm_unittest_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmUnitTestSourceField,
        HelmUnitTestDependenciesField,
        HelmUnitTestStrictField,
        HelmUnitTestTimeoutField,
    )
    help = "A single helm-unittest suite file."


class AllHelmUnitTestTestTargets(Targets):
    pass


@rule
def all_helm_unittest_test_targets(all_targets: AllTargets) -> AllHelmUnitTestTestTargets:
    return AllHelmUnitTestTestTargets(
        [tgt for tgt in all_targets if tgt.has_field(HelmUnitTestSourceField)]
    )


# -----------------------------------------------------------------------------------------------
# `helm_unittest_tests` target generator
# -----------------------------------------------------------------------------------------------


class HelmUnitTestGeneratingSourcesField(MultipleSourcesField):
    default = ("*_test.yaml",)
    expected_file_extensions = (
        ".yaml",
        ".yml",
    )
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['*_test.yaml', '!ignore_test.yaml']`"
    )


class HelmUnitTestOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        HelmUnitTestTestTarget.alias,
        """
        overrides={
            "configmap_test.yaml": {"timeout": 120},
            ("deployment_test.yaml", "pod_test.yaml"): {"tags": ["slow_tests"]},
        }
        """,
    )


class HelmUnitTestTestsGeneratorTarget(TargetFilesGenerator):
    alias = "helm_unittest_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmUnitTestGeneratingSourcesField,
        HelmUnitTestDependenciesField,
        HelmUnitTestOverridesField,
    )
    generated_target_cls = HelmUnitTestTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        HelmUnitTestDependenciesField,
        HelmUnitTestStrictField,
        HelmUnitTestTimeoutField,
    )
    help = f"Generates a `{HelmUnitTestTestTarget.alias}` target per each file in the `{HelmUnitTestGeneratingSourcesField.alias}` field."


# -----------------------------------------------------------------------------------------------
# `helm_artifact` target
# -----------------------------------------------------------------------------------------------


class HelmArtifactRegistryField(StringField):
    alias = "registry"
    help = softwrap(
        """
        Either registry alias (prefixed by `@`) configured in `[helm.registries]` for the
        Helm artifact or the full OCI registry URL.
        """
    )


class HelmArtifactRepositoryField(StringField):
    alias = "repository"
    help = softwrap(
        f"""
        Either a HTTP(S) URL to a classic repository, or a path inside an OCI registry (when
        `{HelmArtifactRegistryField.alias}` is provided).
        """
    )


class HelmArtifactArtifactField(StringField):
    alias = "artifact"
    required = True
    help = "Artifact name of the chart, without version number."


class HelmArtifactVersionField(StringField):
    alias = "version"
    required = True
    help = "The `version` part of a third party Helm chart."


class HelmArtifactTarget(Target):
    alias = "helm_artifact"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmArtifactRegistryField,
        HelmArtifactRepositoryField,
        HelmArtifactArtifactField,
        HelmArtifactVersionField,
    )
    help = "A third party Helm artifact."


@dataclass(frozen=True)
class HelmArtifactFieldSet(FieldSet):
    required_fields = (HelmArtifactArtifactField, HelmArtifactVersionField)

    registry: HelmArtifactRegistryField
    repository: HelmArtifactRepositoryField
    artifact: HelmArtifactArtifactField
    version: HelmArtifactVersionField


class AllHelmArtifactTargets(Targets):
    pass


@rule
def all_helm_artifact_targets(all_targets: AllTargets) -> AllHelmArtifactTargets:
    return AllHelmArtifactTargets(
        [tgt for tgt in all_targets if HelmArtifactFieldSet.is_applicable(tgt)]
    )


# -----------------------------------------------------------------------------------------------
# `helm_deployment` target
# -----------------------------------------------------------------------------------------------


class HelmDeploymentReleaseNameField(StringField):
    alias = "release_name"
    help = "Name of the release used in the deployment. If not set, the target name will be used instead."


class HelmDeploymentNamespaceField(StringField):
    alias = "namespace"
    help = "Kubernetes namespace for the given deployment."


class HelmDeploymentDependenciesField(Dependencies):
    pass


class HelmDeploymentSkipCrdsField(BoolField):
    alias = "skip_crds"
    default = False
    help = "If true, then does not deploy the Custom Resource Definitions that are defined in the chart."


class HelmDeploymentSourcesField(MultipleSourcesField):
    default = ("*.yaml", "*.yml")
    expected_file_extensions = (".yaml", ".yml")
    help = "Helm configuration files for a given deployment."


class HelmDeploymentValuesField(DictStringToStringField):
    alias = "values"
    required = False
    help = softwrap(
        """
        Individual values to use when rendering a given deployment.

        Value names should be defined using dot-syntax as in the following example:

        ```
        helm_deployment(
            values={
                "nameOverride": "my_custom_name",
                "image.pullPolicy": "Always",
            },
        )
        ```

        Values can be dynamically calculated using interpolation as shown in the following example:

        ```
        helm_deployment(
            values={
                "configmap.deployedAt": "{env.DEPLOY_TIME}",
            },
        )
        ```

        Check the Helm backend documentation on what are the options available and its caveats when making
        usage of dynamic values in your deployments.
        """
    )


class HelmDeploymentCreateNamespaceField(BoolField):
    alias = "create_namespace"
    default = False
    help = "If true, the namespace will be created if it doesn't exist."


class HelmDeploymentNoHooksField(BoolField):
    alias = "no_hooks"
    default = False
    help = "If true, none of the lifecycle hooks of the given chart will be included in the deployment."


class HelmDeploymentTimeoutField(IntField):
    alias = "timeout"
    required = False
    help = "Timeout in seconds when running a Helm deployment."
    valid_numbers = ValidNumbers.positive_only


class HelmDeploymentPostRenderersField(SpecialCasedDependencies):
    alias = "post_renderers"
    help = softwrap(
        """
        List of runnable targets to be used to post-process the helm chart after being rendered by Helm.

        This is equivalent to the same post-renderer feature already available in Helm with the difference
        that this supports a list of executables instead of a single one.

        When more than one post-renderer is given, they will be combined into a single one in which the
        input of each of them would be output of the previous one.
        """
    )


class HelmDeploymentTarget(Target):
    alias = "helm_deployment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmDeploymentReleaseNameField,
        HelmDeploymentDependenciesField,
        HelmDeploymentSourcesField,
        HelmDeploymentNamespaceField,
        HelmDeploymentSkipCrdsField,
        HelmDeploymentValuesField,
        HelmDeploymentCreateNamespaceField,
        HelmDeploymentNoHooksField,
        HelmDeploymentTimeoutField,
        HelmDeploymentPostRenderersField,
    )
    help = "A Helm chart deployment."


@dataclass(frozen=True)
class HelmDeploymentFieldSet(FieldSet):
    required_fields = (
        HelmDeploymentDependenciesField,
        HelmDeploymentSourcesField,
    )

    description: DescriptionField
    release_name: HelmDeploymentReleaseNameField
    namespace: HelmDeploymentNamespaceField
    create_namespace: HelmDeploymentCreateNamespaceField
    sources: HelmDeploymentSourcesField
    skip_crds: HelmDeploymentSkipCrdsField
    no_hooks: HelmDeploymentNoHooksField
    dependencies: HelmDeploymentDependenciesField
    values: HelmDeploymentValuesField
    post_renderers: HelmDeploymentPostRenderersField

    def format_values(
        self, interpolation_context: InterpolationContext, *, ignore_missing: bool = False
    ) -> dict[str, str]:
        source = InterpolationContext.TextSource(
            self.address,
            target_alias=HelmDeploymentTarget.alias,
            field_alias=HelmDeploymentValuesField.alias,
        )

        def format_value(text: str) -> str | None:
            try:
                return interpolation_context.format(
                    text,
                    source=source,
                )
            except InterpolationError as err:
                if ignore_missing:
                    return None
                raise err

        result = {}
        for key, value in (self.values.value or {}).items():
            formatted_value = format_value(value)
            if formatted_value is not None:
                result[key] = formatted_value

        return result


class AllHelmDeploymentTargets(Targets):
    pass


@rule
def all_helm_deployment_targets(targets: AllTargets) -> AllHelmDeploymentTargets:
    return AllHelmDeploymentTargets(
        [tgt for tgt in targets if HelmDeploymentFieldSet.is_applicable(tgt)]
    )


def rules():
    return collect_rules()
