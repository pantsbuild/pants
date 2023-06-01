# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.helm.target_types import HelmChartTarget, HelmUnitTestTestTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.test.unittest import HelmUnitTestFieldSet, HelmUnitTestRequest
from pants.backend.helm.test.unittest import rules as unittest_rules
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_TEMPLATE,
)
from pants.backend.helm.util_rules import chart
from pants.core.goals.test import TestResult
from pants.core.util_rules import external_tool, source_files
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.source.source_root import rules as source_root_rules
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmUnitTestTestTarget],
        rules=[
            *external_tool.rules(),
            *chart.rules(),
            *unittest_rules(),
            *source_files.rules(),
            *source_root_rules(),
            *target_types_rules(),
            QueryRule(TestResult, (HelmUnitTestRequest.Batch,)),
        ],
    )


def test_simple_success(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "tests/BUILD": "helm_unittest_test(name='test', source='service_test.yaml')",
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

    target = rule_runner.get_target(Address("tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])

    assert result.exit_code == 0
    assert result.xml_results and result.xml_results.files
    assert result.xml_results.files == (f"{target.address.path_safe_spec}.xml",)


def test_simple_success_with_legacy_tool(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "tests/BUILD": "helm_unittest_test(name='test', source='service_test.yaml')",
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

    rule_runner.set_options(["--helm-unittest-version=0.2.8"])
    target = rule_runner.get_target(Address("tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])

    assert result.exit_code == 0
    assert result.xml_results and result.xml_results.files
    assert result.xml_results.files == (f"{target.address.path_safe_spec}.xml",)


def test_simple_failure(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "tests/BUILD": "helm_unittest_test(name='test', source='service_test.yaml')",
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
                          of: Ingress
                      - equal:
                          path: spec.type
                          value: ClusterIP
                """
            ),
        }
    )

    target = rule_runner.get_target(Address("tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])
    assert result.exit_code == 1
