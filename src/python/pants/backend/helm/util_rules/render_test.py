# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve import artifacts, fetch
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartTarget
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import chart, render, sources, tool
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.render import RenderChartRequest, RenderedChart
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine import process
from pants.engine.fs import CreateDigest, FileContent, Snapshot
from pants.engine.internals.graph import rules as graph_rules
from pants.engine.rules import QueryRule, SubsystemRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget],
        rules=[
            *artifacts.rules(),
            *config_files.rules(),
            *external_tool.rules(),
            *chart.rules(),
            *fetch.rules(),
            *tool.rules(),
            *render.rules(),
            *process.rules(),
            *graph_rules(),
            *stripped_source_files.rules(),
            *sources.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(HelmBinary, ()),
            QueryRule(HelmChart, (HelmChartFieldSet,)),
            QueryRule(RenderedChart, (RenderChartRequest,)),
            QueryRule(Snapshot, (CreateDigest,)),
        ],
    )


def test_template_rendering(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
        }
    )

    values_override = dedent(
        """\
    service:
      externalPort: 1234
    """
    )
    files_snapshot = rule_runner.request(
        Snapshot, [CreateDigest([FileContent("values.yaml", bytes(values_override, "utf-8"))])]
    )

    chart_target = rule_runner.get_target(Address("", target_name="mychart"))
    field_set = HelmChartFieldSet.create(chart_target)

    chart = rule_runner.request(HelmChart, [field_set])
    rendered = rule_runner.request(
        RenderedChart, [RenderChartRequest(chart, value_files=files_snapshot)]
    )

    assert rendered.snapshot
    assert rendered.snapshot.files == (f"{chart.path}/templates/service.yaml",)
