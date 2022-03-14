# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap

import pytest

from pants.backend.helm.dependency_inference.unittest import (
    InjectHelmUnitTestChartDependencyRequest,
)
from pants.backend.helm.dependency_inference.unittest import rules as inject_deps_rules
from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmUnitTestChartField,
    HelmUnitTestTestsGeneratorTarget,
    HelmUnitTestTestTarget,
)
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.testutil import HELM_CHART_FILE, HELM_VALUES_FILE, K8S_SERVICE_FILE
from pants.build_graph.address import Address
from pants.engine.rules import QueryRule
from pants.engine.target import InjectedDependencies
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmUnitTestTestsGeneratorTarget, HelmUnitTestTestTarget],
        rules=[
            *target_types_rules(),
            *inject_deps_rules(),
            QueryRule(InjectedDependencies, (InjectHelmUnitTestChartDependencyRequest,)),
        ],
    )


def test_injects_chart_as_special_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": textwrap.dedent(
                """\
                helm_chart(name="foo")
                """
            ),
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
            "tests/BUILD": textwrap.dedent(
                """\
                helm_unittest_tests(name="foo_tests", sources=["*_test.yaml"])
                """
            ),
            "tests/service_test.yaml": "",
        }
    )

    chart_tgt = rule_runner.get_target(Address("", target_name="foo"))
    unittest_tgt = rule_runner.get_target(Address("tests", target_name="foo_tests"))
    injected_deps = rule_runner.request(
        InjectedDependencies,
        [InjectHelmUnitTestChartDependencyRequest(unittest_tgt[HelmUnitTestChartField])],
    )

    assert len(injected_deps) == 1
    assert list(injected_deps)[0] == chart_tgt.address
