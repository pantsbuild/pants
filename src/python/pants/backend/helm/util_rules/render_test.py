# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest
import yaml

from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import chart, render, tool
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.render import RenderedHelmChart, RenderHelmChartRequest
from pants.core.util_rules import external_tool, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    PathGlobs,
    Snapshot,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget],
        rules=[
            *external_tool.rules(),
            *chart.rules(),
            *render.rules(),
            *stripped_source_files.rules(),
            *tool.rules(),
            QueryRule(HelmChart, (HelmChartRequest,)),
            QueryRule(RenderedHelmChart, (RenderHelmChartRequest,)),
            QueryRule(Snapshot, (CreateDigest,)),
        ],
    )


def test_template_rendering(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='foo')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
        }
    )

    values_files_override = dedent(
        """\
        service:
          externalPort: 1234
        """
    )
    value_files_snapshot = rule_runner.request(
        Snapshot, [CreateDigest([FileContent("values.yaml", values_files_override.encode())])]
    )

    values = {"service.name": "bar"}

    target = rule_runner.get_target(Address("", target_name="foo"))
    chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])
    rendered = rule_runner.request(
        RenderedHelmChart,
        [RenderHelmChartRequest(chart, value_files=value_files_snapshot, values=values)],
    )

    assert rendered.snapshot
    assert rendered.snapshot.files == (f"{chart.path}/templates/service.yaml",)

    rendered_service_digest = rule_runner.request(
        Digest,
        [
            DigestSubset(
                rendered.snapshot.digest, PathGlobs([f"{chart.path}/templates/service.yaml"])
            )
        ],
    )
    rendered_service_contents = rule_runner.request(DigestContents, [rendered_service_digest])

    assert len(rendered_service_contents) == 1
    parsed_service = yaml.safe_load(rendered_service_contents[0].content.decode())
    assert parsed_service["spec"]["ports"][0]["name"] == "bar"
    assert parsed_service["spec"]["ports"][0]["port"] == 1234
