# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartLintStrictField
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.build_graph.address import Address
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmLintFieldSet(HelmChartFieldSet):
    lint_strict: HelmChartLintStrictField


class HelmLintRequest(LintTargetsRequest):
    field_set_type = HelmLintFieldSet
    name = HelmSubsystem.options_scope


@rule(desc="Lint Helm charts", level=LogLevel.DEBUG)
async def run_helm_lint(
    request: HelmLintRequest, helm_subsystem: HelmSubsystem, helm_binary: HelmBinary
) -> LintResults:
    chart_targets = await MultiGet(
        Get(WrappedTarget, Address, field_set.address) for field_set in request.field_sets
    )
    charts = await MultiGet(
        Get(HelmChart, HelmChartFieldSet, HelmChartFieldSet.create(wrapped.target))
        for wrapped in chart_targets
    )
    logger.debug(f"Linting {pluralize(len(charts), 'chart')}...")

    process_results = await MultiGet(
        Get(
            FallibleProcessResult,
            Process,
            helm_binary.lint(
                name=chart.metadata.name,
                path=chart.path,
                digest=chart.snapshot.digest,
                strict=chart.lint_strict or helm_subsystem.lint_strict,
            ),
        )
        for chart in charts
    )
    results = [
        LintResult.from_fallible_process_result(process_result)
        for process_result in process_results
    ]
    return LintResults(results, linter_name=request.name)


def rules():
    return [*collect_rules(), UnionRule(LintTargetsRequest, HelmLintRequest)]
