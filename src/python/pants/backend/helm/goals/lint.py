# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartLintStrictField,
    HelmSkipLintField,
)
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmLintFieldSet(HelmChartFieldSet):
    lint_strict: HelmChartLintStrictField
    skip_lint: HelmSkipLintField


class HelmLintRequest(LintTargetsRequest):
    field_set_type = HelmLintFieldSet
    name = HelmSubsystem.options_scope


@rule(desc="Lint Helm charts", level=LogLevel.DEBUG)
async def run_helm_lint(request: HelmLintRequest, helm_subsystem: HelmSubsystem) -> LintResults:
    charts = await MultiGet(
        Get(HelmChart, HelmChartRequest(field_set))
        for field_set in request.field_sets
        if not field_set.skip_lint.value
    )
    logger.debug(f"Linting {pluralize(len(charts), 'chart')}...")

    def create_process(chart: HelmChart, field_set: HelmLintFieldSet) -> HelmProcess:
        argv = ["lint", chart.path]

        strict: bool = field_set.lint_strict.value or helm_subsystem.lint_strict
        if strict:
            argv.append("--strict")

        return HelmProcess(
            argv,
            input_digest=chart.snapshot.digest,
            description=f"Linting chart: {chart.metadata.name}",
        )

    process_results = await MultiGet(
        Get(
            FallibleProcessResult,
            HelmProcess,
            create_process(chart, field_set),
        )
        for chart, field_set in zip(charts, request.field_sets)
    )
    results = [
        LintResult.from_fallible_process_result(
            process_result, partition_description=chart.metadata.name
        )
        for chart, process_result in zip(charts, process_results)
    ]
    return LintResults(results, linter_name=request.name)


def rules():
    return [*collect_rules(), UnionRule(LintTargetsRequest, HelmLintRequest)]
