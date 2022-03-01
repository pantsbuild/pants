# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from abc import ABCMeta
from dataclasses import dataclass
from textwrap import dedent

from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TriBoolField,
)
from pants.util.docutil import bin_name

# -----------------------------------------------------------------------------------------------
# Generic commonly used fields
# -----------------------------------------------------------------------------------------------


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
    help = "If set to true, enables strict linting of this Helm chart"


class HelmChartTarget(Target):
    alias = "helm_chart"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmChartMetaSourceField,
        HelmChartSourcesField,
        HelmChartDependenciesField,
        HelmChartOutputPathField,
        HelmChartLintStrictField,
        HelmSkipPushField,
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
    lint_strict: HelmChartLintStrictField
