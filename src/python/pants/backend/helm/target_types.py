# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.core.goals.package import OutputPathField
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    BoolField,
    Dependencies,
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    Targets,
    TriBoolField,
)
from pants.util.docutil import bin_name

# -----------------------------------------------------------------------------------------------
# Generic commonly used fields
# -----------------------------------------------------------------------------------------------


class HelmSkipPushField(BoolField):
    alias = "skip_push"
    default = False
    help = (
        "If set to true, do not push this helm chart "
        f"to registries when running `{bin_name()} publish`."
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
    help = "The chart definition file"


class HelmChartSourcesField(MultipleSourcesField):
    default = ("values.yaml", "templates/*.yaml", "templates/*.tpl")
    expected_file_extensions = (".yaml", ".yml", ".tpl")


class HelmChartDependenciesField(Dependencies):
    pass


class HelmChartOutputPathField(OutputPathField):
    help = (
        "Where the built directory tree should be located.\n\n"
        "If undefined, this will use the path to the BUILD file, "
        "For example, `src/charts/mychart:tgt_name` would be "
        "`src.charts.mychart/tgt_name/`.\n\n"
        "Regardless of whether you use the default or set this field, the path will end with "
        "Helms's file format of `<chart_name>-<chart_version>.tgz`, where "
        "`chart_name` and `chart_version` are the values extracted from the Chart.yaml file. "
        "So, using the default for this field, the target "
        "`src/charts/mychart:tgt_name` might have a final path like "
        "`src.charts.mychart/tgt_name/mychart-0.1.0.tgz`.\n\n"
        f"When running `{bin_name()} package`, this path will be prefixed by `--distdir` (e.g. "
        "`dist/`).\n\n"
        "Warning: setting this value risks naming collisions with other package targets you may "
        "have."
    )


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


class HelmUnitTestSourceField(SingleSourceField):
    expected_file_extensions = (
        ".yaml",
        ".yml",
    )


class HelmUnitTestTestTarget(Target):
    alias = "helm_unittest_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmUnitTestSourceField,
        HelmUnitTestDependenciesField,
    )
    help = "A single helm-unittest suite file"


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


class HelmUnitTestTestsGeneratorTarget(TargetFilesGenerator):
    alias = "helm_unittest_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        HelmUnitTestGeneratingSourcesField,
        HelmUnitTestDependenciesField,
    )
    generated_target_cls = HelmUnitTestTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (HelmUnitTestDependenciesField,)
    help = f"Generates a `{HelmUnitTestTestTarget.alias}` target per each file in the `{HelmUnitTestGeneratingSourcesField.alias}` field"


def rules():
    return collect_rules()
