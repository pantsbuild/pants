# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from abc import ABCMeta
from dataclasses import dataclass
from textwrap import dedent

from pants.backend.helm.resolve.registries import ALL_DEFAULT_HELM_REGISTRIES
from pants.core.goals.package import OutputPathField
from pants.engine.fs import GlobMatchErrorBehavior
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    DescriptionField,
    DictStringToStringField,
    FieldSet,
    MultipleSourcesField,
    OptionalSingleSourceField,
    SingleSourceField,
    StringField,
    StringSequenceField,
    Target,
    TriBoolField,
)
from pants.util.docutil import bin_name

# -----------------------------------------------------------------------------------------------
# Generic commonly used fields
# -----------------------------------------------------------------------------------------------


class HelmRegistriesField(StringSequenceField):
    alias = "registries"
    default = (ALL_DEFAULT_HELM_REGISTRIES,)
    help = (
        "List of addresses or configured aliases to any OCI registries to use for the "
        "built chart.\n\n"
        "The address is an `oci://` prefixed domain name with optional port for your registry, and any registry "
        "aliases are prefixed with `@` for addresses in the [docker].registries configuration "
        "section.\n\n"
        "By default, all configured registries with `default = true` are used.\n\n"
        + dedent(
            """\
            Example:
                # pants.toml
                [docker.registries.my-registry-alias]
                address = "myregistrydomain:port"
                default = false  # optional
                # example/BUILD
                helm_chart(
                    registries = [
                        "@my-registry-alias",
                        "oci://myregistrydomain:port",
                    ],
                )
            """
        )
        + (
            "The above example shows two valid `registry` options: using an alias to a configured "
            "registry and the address to a registry verbatim in the BUILD file."
        )
    )


class HelmRepositoryField(StringField):
    alias = "repository"
    help = (
        'The repository name for the Helm chart. e.g. "<repository>/<name>".\n\n'
        "It uses the `[helm].default_oci_repository` by default."
        "This field value may contain format strings that will be interpolated at runtime. "
        "See the documentation for `[helm].default_oci_repository` for details."
    )


class HelmSkipPushField(BoolField):
    alias = "skip_push"
    default = False
    help = f"If set to true, do not push this helm chart to registries when running `{bin_name()} publish`."


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
    help = "The chart definition file"


class HelmChartSourcesField(MultipleSourcesField):
    default = ("values.yaml", "templates/*.yaml", "templates/*.tpl")
    expected_file_extensions = (".yaml", ".yml", ".tpl")


class HelmChartReadmeField(OptionalSingleSourceField):
    alias = "readme"
    required = False
    help = "The README.md documentation file for the Chart"

    expected_file_extensions = (".md",)

    default = "README.md"
    default_glob_match_error_behavior = GlobMatchErrorBehavior.warn


class HelmChartDependenciesField(Dependencies):
    pass


class HelmChartOutputPathField(OutputPathField):
    help = dedent(
        """\
        The destination folder where the final packaged chart will be located.\n
        The final package name will still follow Helm convention, this output path will only affect the destination folder where can be found.
        """
    )

    def value_or_default(self, *, file_ending: str | None) -> str:
        if self.value:
            return self.value
        return os.path.join(self.address.spec_path.replace(os.sep, "."))


class HelmChartLintStrictField(TriBoolField):
    alias = "lint_strict"
    help = "Enable or disable strict linting"


class HelmChartTarget(Target):
    alias = "helm_chart"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmChartMetaSourceField,
        HelmChartSourcesField,
        HelmChartReadmeField,
        HelmChartDependenciesField,
        HelmChartOutputPathField,
        HelmChartLintStrictField,
        HelmRegistriesField,
        HelmSkipPushField,
        HelmRepositoryField,
    )
    help = "A Helm chart"


@dataclass(frozen=True)
class HelmChartFieldSet(FieldSet, metaclass=ABCMeta):
    required_fields = (
        HelmChartMetaSourceField,
        HelmChartSourcesField,
    )

    chart: HelmChartMetaSourceField
    sources: HelmChartSourcesField
    dependencies: HelmChartDependenciesField
    readme: HelmChartReadmeField


# -----------------------------------------------------------------------------------------------
# `helm_artifact` target
# -----------------------------------------------------------------------------------------------


class HelmArtifactRegistryField(StringField):
    alias = "registry"
    help = (
        "Registry alias (prefixed by `@`) configured in `[helm.registries]` for the Helm artifact"
    )


class HelmArtifactRepositoryField(StringField):
    alias = "repository"
    help = "Either an alias (prefixed by `@`) to a classic Helm repository configured in `[helm.registries]` or a path inside an OCI registry"


class HelmArtifactArtifactField(StringField):
    alias = "artifact"
    required = True
    help = "Artifact name of the chart, without version number"


class HelmArtifactVersionField(StringField):
    alias = "version"
    required = True
    help = "The `version` part of a third party Helm chart"


class HelmArtifactTarget(Target):
    alias = "helm_artifact"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmArtifactRegistryField,
        HelmArtifactRepositoryField,
        HelmArtifactArtifactField,
        HelmArtifactVersionField,
    )
    help = "A third party Helm artifact"


@dataclass(frozen=True)
class HelmArtifactFieldSet(FieldSet):
    required_fields = (HelmArtifactArtifactField, HelmArtifactVersionField)

    registry: HelmArtifactRegistryField
    repository: HelmArtifactRepositoryField
    artifact: HelmArtifactArtifactField
    version: HelmArtifactVersionField


# -----------------------------------------------------------------------------------------------
# `helm_deployment` target
# -----------------------------------------------------------------------------------------------


class HelmDeploymentReleaseNameField(StringField):
    alias = "release_name"
    help = "Name of the release used in the deployment"


class HelmDeploymentNamespaceField(StringField):
    alias = "namespace"
    help = "Kubernetes namespace for the given deployment"


class HelmDeploymentTimeoutField(StringField):
    alias = "timeout"
    help = "Maximum time to wait when doing an install or rollback of a deployment"


class HelmDeploymentDependenciesField(Dependencies):
    pass


class HelmDeploymentSkipCrdsField(BoolField):
    alias = "skip_crds"
    default = False
    help = "If true, then does not install the Custom Resource Definitions that are defined in the chart"


class HelmDeploymentSourcesField(MultipleSourcesField):
    default = ("*.yaml", "*.yml")
    expected_file_extensions = (".yaml", ".yml")
    help = "Helm configuration files for a given deployment"


class HelmDeploymentValuesField(DictStringToStringField):
    alias = "values"
    required = False
    help = "Individual values to use when rendering a given deployment"


class HelmDeploymentTarget(Target):
    alias = "helm_deployment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmDeploymentReleaseNameField,
        HelmDeploymentDependenciesField,
        HelmDeploymentSourcesField,
        HelmDeploymentNamespaceField,
        HelmDeploymentTimeoutField,
        HelmDeploymentSkipCrdsField,
        HelmDeploymentValuesField,
    )
    help = "A Helm chart deployment"


@dataclass(frozen=True)
class HelmDeploymentFieldSet(FieldSet, metaclass=ABCMeta):
    required_fields = (
        HelmDeploymentDependenciesField,
        HelmDeploymentSourcesField,
    )

    description: DescriptionField
    release_name: HelmDeploymentReleaseNameField
    namespace: HelmDeploymentNamespaceField
    sources: HelmDeploymentSourcesField
    skip_crds: HelmDeploymentSkipCrdsField
    dependencies: HelmDeploymentDependenciesField
    timeout: HelmDeploymentTimeoutField
    values: HelmDeploymentValuesField
