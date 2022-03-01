# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartTarget
from pants.backend.helm.testutil import (
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
    gen_chart_file,
)
from pants.backend.helm.util_rules import chart, sources, tool
from pants.backend.helm.util_rules.chart import ChartType, HelmChart, HelmChartMetadata
from pants.build_graph.address import Address
from pants.core.target_types import FileTarget
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine import process
from pants.engine.rules import QueryRule, SubsystemRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, FileTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *chart.rules(),
            *sources.rules(),
            *tool.rules(),
            *process.rules(),
            *stripped_source_files.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(HelmChart, (HelmChartFieldSet,)),
        ],
    )


chart_type_parameters = [
    ("foo", "0.1.0", ChartType.APPLICATION),
    ("bar", "0.2.0", ChartType.LIBRARY),
]


@pytest.mark.parametrize("name, version, type", chart_type_parameters)
def test_compiles_single_chart_sources(
    rule_runner: RuleRunner, name: str, version: str, type: ChartType
) -> None:
    rule_runner.write_files(
        {
            "BUILD": f"helm_chart(name='{name}')",
            "Chart.yaml": gen_chart_file(name, version=version, type=type),
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
        }
    )

    address = Address("", target_name=name)
    tgt = rule_runner.get_target(address)
    field_set = HelmChartFieldSet.create(tgt)

    expected_metadata = HelmChartMetadata(
        name=name,
        version=version,
        api_version="v2",
        icon="https://www.example.com/icon.png",
        description="A Helm chart for Kubernetes",
        type=type,
    )

    helm_chart = rule_runner.request(HelmChart, [field_set])
    assert helm_chart.metadata == expected_metadata
    assert len(helm_chart.snapshot.files) == 4
    assert helm_chart.address == address


def test_gathers_local_subchart_sources_using_explicit_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart1/BUILD": "helm_chart()",
            "src/chart1/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart1
                version: 0.1.0
                """
            ),
            "src/chart1/values.yaml": HELM_VALUES_FILE,
            "src/chart1/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/chart1/templates/service.yaml": K8S_SERVICE_FILE,
            "src/chart2/BUILD": "helm_chart(dependencies=['//src/chart1'])",
            "src/chart2/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart2
                version: 0.1.0
                dependencies:
                - name: chart1
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/chart2", target_name="chart2"))
    field_set = HelmChartFieldSet.create(target)

    helm_chart = rule_runner.request(HelmChart, [field_set])
    assert "chart2/charts/chart1" in helm_chart.snapshot.dirs
    assert "chart2/charts/chart1/templates/service.yaml" in helm_chart.snapshot.files
