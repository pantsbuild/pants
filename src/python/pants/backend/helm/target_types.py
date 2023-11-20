# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

from pants.backend.helm.resolve.remotes import ALL_DEFAULT_HELM_REGISTRIES
from pants.base.deprecated import deprecated, warn_or_error
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.goals.package import OutputPathField
from pants.core.goals.test import TestTimeoutField
from pants.engine.internals.native_engine import AddressInput
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    AsyncFieldMixin,
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
from pants.util.memo import memoized_method
from pants.util.strutil import help_text, softwrap
from pants.util.value_interpolation import InterpolationContext, InterpolationError

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Generic commonly used fields
# -----------------------------------------------------------------------------------------------


class HelmRegistriesField(StringSequenceField):
    alias = "registries"
    default = (ALL_DEFAULT_HELM_REGISTRIES,)
    help = help_text(
        """
        List of addresses or configured aliases to any OCI registries to use for the
        built chart.

        The address is an `oci://` prefixed domain name with optional port for your registry, and any registry
        aliases are prefixed with `@` for addresses in the `[helm].registries` configuration
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
    help = help_text(
        f"""
        If set to true, do not run any linting in this Helm chart when running `{bin_name()}
        lint`.
        """
    )


class HelmSkipPushField(BoolField):
    alias = "skip_push"
    default = False
    help = help_text(
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
    help = help_text(
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
    help = help_text(
        """
        Repository to use in the Helm registry where this chart is going to be published.

        If no value is given and `[helm].default-registry-repository` is undefined too, then the chart
        will be pushed to the root of the OCI registry.
        """
    )


class HelmChartVersionField(StringField):
    alias = "version"
    help = help_text(
        """
        Version number for the given Helm chart.

        When specified, the version provided in the source Chart.yaml file will be overriden by the value
        given to this field.
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
        HelmChartVersionField,
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
    description: DescriptionField
    version: HelmChartVersionField


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
    default = ("*_test.yaml", "*_test.yml")
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
        HelmUnitTestStrictField,
        HelmUnitTestTimeoutField,
    )
    help = f"Generates a `{HelmUnitTestTestTarget.alias}` target per each file in the `{HelmUnitTestGeneratingSourcesField.alias}` field."


# -----------------------------------------------------------------------------------------------
# `helm_artifact` target
# -----------------------------------------------------------------------------------------------


class HelmArtifactRegistryField(StringField):
    alias = "registry"
    help = help_text(
        """
        Either registry alias (prefixed by `@`) configured in `[helm.registries]` for the
        Helm artifact or the full OCI registry URL.
        """
    )


class HelmArtifactRepositoryField(StringField):
    alias = "repository"
    help = help_text(
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


class HelmDeploymentChartField(StringField, AsyncFieldMixin):
    alias = "chart"
    # TODO Will be made required in next release
    required = False
    help = help_text(
        f"""
        The address of the `{HelmChartTarget.alias}` or `{HelmArtifactTarget.alias}`
        that will be used for this deployment.
        """
    )

    def to_address_input(self) -> AddressInput | None:
        if self.value:
            return AddressInput.parse(
                self.value,
                relative_to=self.address.spec_path,
                description_of_origin=f"the `{self.alias}` field in the `{HelmDeploymentTarget.alias}` target {self.address}",
            )

        warn_or_error(
            "2.19.0.dev0",
            "chart address in `dependencies`",
            softwrap(
                f"""
                You should specify the chart address in the new `{self.alias}` field in
                {HelmDeploymentTarget.alias}. In future versions this will be mandatory.
                """
            ),
            start_version="2.18.0.dev1",
        )
        return None


class HelmDeploymentReleaseNameField(StringField):
    alias = "release_name"
    help = "Name of the release used in the deployment. If not set, the target name will be used instead."


class HelmDeploymentNamespaceField(StringField):
    alias = "namespace"
    help = help_text("""Kubernetes namespace for the given deployment.""")


class HelmDeploymentDependenciesField(Dependencies):
    pass


class HelmDeploymentSkipCrdsField(BoolField):
    alias = "skip_crds"
    default = False
    help = "If true, then does not deploy the Custom Resource Definitions that are defined in the chart."


class HelmDeploymentSourcesField(MultipleSourcesField):
    default = ("*.yaml", "*.yml")
    expected_file_extensions = (".yaml", ".yml")
    default_glob_match_error_behavior = GlobMatchErrorBehavior.ignore
    help = "Helm configuration files for a given deployment."


class HelmDeploymentValuesField(DictStringToStringField, AsyncFieldMixin):
    alias = "values"
    required = False
    help = help_text(
        """
        Individual values to use when rendering a given deployment.

        Value names should be defined using dot-syntax as in the following example:

            helm_deployment(
                values={
                    "nameOverride": "my_custom_name",
                    "image.pullPolicy": "Always",
                },
            )

        Values can be dynamically calculated using interpolation as shown in the following example:

            helm_deployment(
                values={
                    "configmap.deployedAt": f"{env('DEPLOY_TIME')}",
                },
            )

        Check the Helm backend documentation on what are the options available and its caveats when making
        usage of dynamic values in your deployments.
        """
    )

    @memoized_method
    @deprecated("2.19.0.dev0", start_version="2.18.0.dev0")
    def format_with(
        self, interpolation_context: InterpolationContext, *, ignore_missing: bool = False
    ) -> dict[str, str]:
        return self._format_with(interpolation_context, ignore_missing=ignore_missing)

    def _format_with(
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
        default_curr_value: dict[str, str] = {}
        current_value: Mapping[str, str] = self.value or default_curr_value
        for key, value in current_value.items():
            formatted_value = format_value(value)
            if formatted_value is not None:
                result[key] = formatted_value

        if result != current_value:
            warn_or_error(
                "2.19.0.dev0",
                "Using the {env.VAR_NAME} interpolation syntax",
                "Use the new `f\"prefix-{env('VAR_NAME')}\" syntax for interpolating values from environment variables.",
                start_version="2.18.0.dev0",
            )

        return result


class HelmDeploymentCreateNamespaceField(BoolField):
    alias = "create_namespace"
    default = False
    help = "If true, the namespace will be created if it doesn't exist."

    removal_version = "2.19.0.dev0"
    # TODO This causes and error in the parser as it believes it is using it as the `removal_version` attribute.
    # removal_hint = "Use the passthrough argument `--create-namespace` instead."


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
    help = help_text(
        """
        List of runnable targets to be used to post-process the helm chart after being rendered by Helm.

        This is equivalent to the same post-renderer feature already available in Helm with the difference
        that this supports a list of executables instead of a single one.

        When more than one post-renderer is given, they will be combined into a single one in which the
        input of each of them would be output of the previous one.
        """
    )


class HelmDeploymentEnableDNSField(BoolField):
    alias = "enable_dns"
    default = False
    help = "Enables DNS lookups when using the `getHostByName` template function."


class HelmDeploymentTarget(Target):
    alias = "helm_deployment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmDeploymentChartField,
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
        HelmDeploymentEnableDNSField,
    )
    help = "A Helm chart deployment."


@dataclass(frozen=True)
class HelmDeploymentFieldSet(FieldSet):
    required_fields = (
        HelmDeploymentDependenciesField,
        HelmDeploymentSourcesField,
    )

    chart: HelmDeploymentChartField
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
    enable_dns: HelmDeploymentEnableDNSField

    @deprecated(
        "2.19.0.dev0", "Use `field_set.values.format_with()` instead.", start_version="2.18.0.dev0"
    )
    def format_values(
        self, interpolation_context: InterpolationContext, *, ignore_missing: bool = False
    ) -> dict[str, str]:
        return self.values._format_with(interpolation_context, ignore_missing=ignore_missing)


class AllHelmDeploymentTargets(Targets):
    pass


@rule
def all_helm_deployment_targets(targets: AllTargets) -> AllHelmDeploymentTargets:
    return AllHelmDeploymentTargets(
        [tgt for tgt in targets if HelmDeploymentFieldSet.is_applicable(tgt)]
    )


def rules():
    return collect_rules()
