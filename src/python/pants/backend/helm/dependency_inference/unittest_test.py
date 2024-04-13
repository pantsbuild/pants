# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap

import pytest

from pants.backend.helm.dependency_inference.unittest import (
    HelmUnitTestChartDependencyInferenceFieldSet,
    InferHelmUnitTestChartDependencyRequest,
)
from pants.backend.helm.dependency_inference.unittest import rules as infer_deps_rules
from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmUnitTestTestsGeneratorTarget,
    HelmUnitTestTestTarget,
)
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_TEMPLATE,
    gen_chart_file,
)
from pants.build_graph.address import Address
from pants.core.target_types import ResourcesGeneratorTarget, ResourceTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[
            HelmChartTarget,
            HelmUnitTestTestsGeneratorTarget,
            HelmUnitTestTestTarget,
            ResourceTarget,
            ResourcesGeneratorTarget,
        ],
        rules=[
            *target_types_rules(),
            *core_target_types_rules(),
            *infer_deps_rules(),
            QueryRule(InferredDependencies, (InferHelmUnitTestChartDependencyRequest,)),
        ],
    )


def test_infers_single_chart(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": textwrap.dedent(
                """\
                helm_chart(name="foo")
                """
            ),
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
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
    inferred_deps = rule_runner.request(
        InferredDependencies,
        [
            InferHelmUnitTestChartDependencyRequest(
                HelmUnitTestChartDependencyInferenceFieldSet.create(unittest_tgt)
            )
        ],
    )

    assert inferred_deps == InferredDependencies([chart_tgt.address])


def test_injects_parent_chart(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart1/BUILD": """helm_chart()""",
            "src/chart1/Chart.yaml": gen_chart_file("chart1", version="0.1.0"),
            "src/chart1/values.yaml": HELM_VALUES_FILE,
            "src/chart1/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/chart1/tests/BUILD": """helm_unittest_tests(sources=["*_test.yaml"])""",
            "src/chart1/tests/service_test.yaml": "",
            "src/chart2/BUILD": """helm_chart()""",
            "src/chart2/Chart.yaml": gen_chart_file("chart2", version="0.1.0"),
            "src/chart2/values.yaml": HELM_VALUES_FILE,
            "src/chart2/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/chart2/tests/BUILD": """helm_unittest_tests(sources=["*_test.yaml"])""",
            "src/chart2/tests/service_test.yaml": "",
        }
    )

    chart1_tgt = rule_runner.get_target(Address("src/chart1", target_name="chart1"))
    chart1_unittest_tgt = rule_runner.get_target(Address("src/chart1/tests", target_name="tests"))

    chart2_tgt = rule_runner.get_target(Address("src/chart2", target_name="chart2"))
    chart2_unittest_tgt = rule_runner.get_target(Address("src/chart2/tests", target_name="tests"))

    chart1_inferred_deps = rule_runner.request(
        InferredDependencies,
        [
            InferHelmUnitTestChartDependencyRequest(
                HelmUnitTestChartDependencyInferenceFieldSet.create(chart1_unittest_tgt)
            )
        ],
    )
    chart2_inferred_deps = rule_runner.request(
        InferredDependencies,
        [
            InferHelmUnitTestChartDependencyRequest(
                HelmUnitTestChartDependencyInferenceFieldSet.create(chart2_unittest_tgt)
            )
        ],
    )

    assert chart1_inferred_deps == InferredDependencies([chart1_tgt.address])
    assert chart2_inferred_deps == InferredDependencies([chart2_tgt.address])


def test_infer_snapshot_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": textwrap.dedent(
                """\
                helm_chart(name="foo")
                """
            ),
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "tests/BUILD": textwrap.dedent(
                """\
                helm_unittest_tests(name="foo_tests", sources=["*_test.yaml"])
                """
            ),
            "tests/service_test.yaml": "",
            "tests/__snapshot__/BUILD": """resources(sources=["*.snap"])""",
            "tests/__snapshot__/service_test.yaml.snap": "",
        }
    )

    chart_tgt = rule_runner.get_target(Address("", target_name="foo"))
    unittest_tgt = rule_runner.get_target(Address("tests", target_name="foo_tests"))
    snapshot_tgt = rule_runner.get_target(
        Address("tests/__snapshot__", relative_file_path="service_test.yaml.snap")
    )

    inferred_deps = rule_runner.request(
        InferredDependencies,
        [
            InferHelmUnitTestChartDependencyRequest(
                HelmUnitTestChartDependencyInferenceFieldSet.create(unittest_tgt)
            )
        ],
    )

    assert inferred_deps == InferredDependencies([chart_tgt.address, snapshot_tgt.address])


def test_discard_explicit_snapshot_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": textwrap.dedent(
                """\
                helm_chart(name="foo")
                """
            ),
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "tests/BUILD": textwrap.dedent(
                """\
                helm_unittest_tests(
                    name="foo_tests",
                    sources=["*_test.yaml"],
                    dependencies=["!tests/__snapshot__/service_test.yaml.snap"]
                )
                """
            ),
            "tests/service_test.yaml": "",
            "tests/__snapshot__/BUILD": """resources(sources=["*.snap"])""",
            "tests/__snapshot__/service_test.yaml.snap": "",
        }
    )

    chart_tgt = rule_runner.get_target(Address("", target_name="foo"))
    unittest_tgt = rule_runner.get_target(Address("tests", target_name="foo_tests"))

    inferred_deps = rule_runner.request(
        InferredDependencies,
        [
            InferHelmUnitTestChartDependencyRequest(
                HelmUnitTestChartDependencyInferenceFieldSet.create(unittest_tgt)
            )
        ],
    )

    assert inferred_deps == InferredDependencies([chart_tgt.address])
