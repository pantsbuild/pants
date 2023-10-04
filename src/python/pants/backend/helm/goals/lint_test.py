# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

import pytest

from pants.backend.helm.goals.lint import HelmLintFieldSet, HelmLintRequest
from pants.backend.helm.goals.lint import rules as helm_lint_rules
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.testutil import (
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_INGRESS_TEMPLATE_WITH_LINT_WARNINGS,
    K8S_SERVICE_TEMPLATE,
    gen_chart_file,
)
from pants.backend.helm.util_rules import chart, sources
from pants.build_graph.address import Address
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, source_files
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.source.source_root import rules as source_root_rules
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[HelmChartTarget],
        rules=[
            *config_files.rules(),
            *chart.rules(),
            *helm_lint_rules(),
            *source_files.rules(),
            *source_root_rules(),
            *sources.rules(),
            *target_types_rules(),
            *HelmSubsystem.rules(),
            QueryRule(Partitions, [HelmLintRequest.PartitionRequest]),
            QueryRule(LintResult, [HelmLintRequest.Batch]),
        ],
    )
    return rule_runner


def run_helm_lint(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_options: Iterable[str] = [],
) -> tuple[LintResult, ...]:
    rule_runner.set_options(extra_options)
    partitions = rule_runner.request(
        Partitions[HelmLintFieldSet, chart.HelmChart],
        [HelmLintRequest.PartitionRequest(tuple(HelmLintFieldSet.create(tgt) for tgt in targets))],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [HelmLintRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def test_lint_non_strict_chart_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": gen_chart_file("mychart", version="0.1.0", icon=None),
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="mychart"))
    lint_results = run_helm_lint(rule_runner, [tgt])

    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].partition_description == "mychart"


def test_lint_non_strict_chart_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": gen_chart_file("mychart", version="0.1.0", icon="wrong URL"),
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="mychart"))
    lint_results = run_helm_lint(rule_runner, [tgt])

    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1


def test_lint_strict_chart_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart', lint_strict=True)",
            "Chart.yaml": gen_chart_file("mychart", version="0.1.0", icon=None),
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/ingress.yaml": K8S_INGRESS_TEMPLATE_WITH_LINT_WARNINGS,
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="mychart"))
    lint_results = run_helm_lint(rule_runner, [tgt])

    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1


def test_global_lint_strict_chart_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": gen_chart_file("mychart", version="0.1.0", icon=None),
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/ingress.yaml": K8S_INGRESS_TEMPLATE_WITH_LINT_WARNINGS,
        }
    )

    extra_opts = ["--helm-lint-strict"]
    tgt = rule_runner.get_target(Address("", target_name="mychart"))
    lint_results = run_helm_lint(rule_runner, [tgt], extra_options=extra_opts)

    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1


def test_lint_strict_chart_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart', lint_strict=True)",
            "Chart.yaml": gen_chart_file("mychart", version="0.1.0", icon=None),
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="mychart"))
    lint_results = run_helm_lint(rule_runner, [tgt])

    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0


def test_one_lint_result_per_chart(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart1/BUILD": "helm_chart()",
            "src/chart1/Chart.yaml": gen_chart_file("chart1", version="0.1.0"),
            "src/chart1/values.yaml": HELM_VALUES_FILE,
            "src/chart1/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/chart1/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/chart2/BUILD": "helm_chart()",
            "src/chart2/Chart.yaml": gen_chart_file("chart2", version="0.1.0"),
            "src/chart2/values.yaml": HELM_VALUES_FILE,
            "src/chart2/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/chart2/templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    chart1_target = rule_runner.get_target(Address("src/chart1", target_name="chart1"))
    chart2_target = rule_runner.get_target(Address("src/chart2", target_name="chart2"))

    lint_results = run_helm_lint(
        rule_runner,
        [chart1_target, chart2_target],
    )
    assert len(lint_results) == 2
    assert lint_results[0].exit_code == 0
    assert lint_results[0].partition_description == "chart1"
    assert lint_results[1].exit_code == 0
    assert lint_results[1].partition_description == "chart2"


def test_skip_lint(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart/BUILD": "helm_chart(skip_lint=True)",
            "src/chart/Chart.yaml": gen_chart_file("chart", version="0.1.0"),
            "src/chart/values.yaml": HELM_VALUES_FILE,
            "src/chart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/chart/templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    chart_target = rule_runner.get_target(Address("src/chart", target_name="chart"))
    lint_results = run_helm_lint(
        rule_runner,
        [chart_target],
    )
    assert len(lint_results) == 0
