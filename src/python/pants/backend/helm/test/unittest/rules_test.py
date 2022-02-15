# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.goals.package import rules as helm_package_rules
from pants.backend.helm.resolve import artifacts, fetch
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.test.unittest.rules import HelmUnitTestFieldSet
from pants.backend.helm.test.unittest.rules import rules as test_rules
from pants.backend.helm.test.unittest.subsystem import rules as unittest_rules
from pants.backend.helm.test.unittest.target_types import HelmUnitTestsTarget
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import chart, sources, tool
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine.internals.graph import rules as graph_rules
from pants.engine.rules import QueryRule, SubsystemRule
from pants.source.source_root import rules as source_root_rules
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmUnitTestsTarget],
        rules=[
            *artifacts.rules(),
            *config_files.rules(),
            *external_tool.rules(),
            *fetch.rules(),
            *tool.rules(),
            *chart.rules(),
            *helm_package_rules(),
            *stripped_source_files.rules(),
            *source_root_rules(),
            *graph_rules(),
            *test_rules(),
            *unittest_rules(),
            *sources.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(TestResult, (HelmUnitTestFieldSet,)),
        ],
    )


def test_simple_success(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "README.md": "",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
            "tests/BUILD": "helm_unittest_tests(name='tests', dependencies=['//:mychart'])",
            "tests/service_test.yaml": dedent(
                """\
          suite: test service
          templates:
            - service.yaml
          values:
            - ../values.yaml
          tests:
            - it: should work
              asserts:
                - isKind:
                    of: Service
                - equal:
                    path: spec.type
                    value: ClusterIP
        """
            ),
        }
    )

    target = rule_runner.get_target(Address("tests", target_name="tests"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [field_set])

    assert result.exit_code == 0
    assert result.xml_results and result.xml_results.files
