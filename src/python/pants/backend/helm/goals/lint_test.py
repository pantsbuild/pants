# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Sequence

import pytest

from pants.backend.helm.goals.lint import HelmLintFieldSet, HelmLintRequest
from pants.backend.helm.goals.lint import rules as helm_lint_rules
from pants.backend.helm.resolve import artifacts, fetch
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import chart, sources, tool
from pants.build_graph.address import Address
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine.rules import QueryRule, SubsystemRule
from pants.engine.target import Target
from pants.source.source_root import rules as source_root_rules
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[HelmChartTarget],
        rules=[
            *artifacts.rules(),
            *config_files.rules(),
            *chart.rules(),
            *external_tool.rules(),
            *fetch.rules(),
            *helm_lint_rules(),
            *tool.rules(),
            *stripped_source_files.rules(),
            *source_root_rules(),
            *sources.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(LintResults, (HelmLintRequest,)),
        ],
    )
    return rule_runner


def run_helm_lint(
    rule_runner: RuleRunner, targets: list[Target], *, source_root_patterns: Sequence[str] = ("/",)
) -> tuple[LintResult, ...]:
    field_sets = [HelmLintFieldSet.create(tgt) for tgt in targets]
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])
    lint_results = rule_runner.request(LintResults, [HelmLintRequest(field_sets)])
    return lint_results.results


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="mychart"))
    lint_results = run_helm_lint(rule_runner, [tgt])

    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0


def test_partitions(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart1/BUILD": "helm_chart()",
            "src/chart1/Chart.yaml": HELM_CHART_FILE,
            "src/chart1/values.yaml": HELM_VALUES_FILE,
            "src/chart1/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/chart1/templates/service.yaml": K8S_SERVICE_FILE,
            "src/chart2/BUILD": "helm_chart()",
            "src/chart2/Chart.yaml": HELM_CHART_FILE,
            "src/chart2/values.yaml": HELM_VALUES_FILE,
            "src/chart2/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/chart2/templates/service.yaml": K8S_SERVICE_FILE,
        }
    )
    source_root_patterns = ("src/*",)

    chart1_target = rule_runner.get_target(Address("src/chart1", target_name="chart1"))
    chart2_target = rule_runner.get_target(Address("src/chart2", target_name="chart2"))

    lint_results = run_helm_lint(
        rule_runner, [chart1_target, chart2_target], source_root_patterns=source_root_patterns
    )
    assert len(lint_results) == 2
    assert lint_results[0].exit_code == 0
    assert lint_results[1].exit_code == 0
