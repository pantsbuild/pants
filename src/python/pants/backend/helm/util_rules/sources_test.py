# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import sources
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.build_graph.address import Address
from pants.core.target_types import FileTarget, ResourceTarget
from pants.core.util_rules import stripped_source_files
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, ResourceTarget, FileTarget],
        rules=[
            *sources.rules(),
            *stripped_source_files.rules(),
            QueryRule(HelmChartSourceFiles, (HelmChartSourceFilesRequest,)),
        ],
    )


def test_collects_resource_sources_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                helm_chart(name='mychart', dependencies=[':xml'])
                resource(name="xml", source='xml_file.xml')
                """
            ),
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
            "xml_file.xml": "",
        }
    )

    address = Address("", target_name="mychart")
    tgt = rule_runner.get_target(address)
    source_files = rule_runner.request(
        HelmChartSourceFiles, [HelmChartSourceFilesRequest.create(tgt)]
    )

    assert "xml_file.xml" in source_files.snapshot.files
