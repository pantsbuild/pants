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
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.goals.lint import LintResult, LintTargetsRequest, TargetPartitions
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmLintFieldSet(HelmChartFieldSet):
    lint_strict: HelmChartLintStrictField
    skip_lint: HelmSkipLintField


class HelmLintRequest(LintTargetsRequest):
    field_set_type = HelmLintFieldSet
    name = HelmSubsystem.options_scope


@rule
async def partition_helm_lint(request: HelmLintRequest.PartitionRequest) -> TargetPartitions:
    return TargetPartitions.from_elements(
        [fs] for fs in request.field_sets if not fs.skip_lint.value
    )


@rule(desc="Lint Helm charts", level=LogLevel.DEBUG)
async def run_helm_lint(
    request: HelmLintRequest.Batch, helm_subsystem: HelmSubsystem
) -> LintResult:
    assert len(request.field_sets) == 1
    field_set = request.field_sets[0]
    chart = await Get(HelmChart, HelmChartRequest(field_set))

    argv = ["lint", chart.name]

    strict = field_set.lint_strict.value or helm_subsystem.lint_strict
    if strict:
        argv.append("--strict")

    process_result = await Get(
        FallibleProcessResult,
        HelmProcess(
            argv,
            extra_immutable_input_digests=chart.immutable_input_digests,
            description=f"Linting chart: {chart.info.name}",
        ),
    )
    return LintResult.from_fallible_process_result(
        process_result, linter_name=HelmSubsystem.options_scope
    )


def rules():
    return [*collect_rules(), *tool.rules(), *HelmLintRequest.registration_rules()]
