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
from pants.core.goals.lint import LintResult, LintTargetsRequest, Partitions
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmLintFieldSet(HelmChartFieldSet):
    lint_strict: HelmChartLintStrictField
    skip_lint: HelmSkipLintField


class HelmLintRequest(LintTargetsRequest):
    field_set_type = HelmLintFieldSet
    tool_subsystem = HelmSubsystem  # type: ignore[assignment]


@rule
async def partition_helm_lint(
    request: HelmLintRequest.PartitionRequest[HelmLintFieldSet],
) -> Partitions[HelmChart, HelmLintFieldSet]:
    field_sets = tuple(
        field_set for field_set in request.field_sets if not field_set.skip_lint.value
    )
    charts = await MultiGet(Get(HelmChart, HelmChartRequest(field_set)) for field_set in field_sets)
    return Partitions((chart, (field_set,)) for chart, field_set in zip(charts, field_sets))


@rule(desc="Lint Helm charts", level=LogLevel.DEBUG)
async def run_helm_lint(
    request: HelmLintRequest.Batch[HelmChart, HelmLintFieldSet],
    helm_subsystem: HelmSubsystem,
) -> LintResult:
    assert len(request.elements) == 1
    field_set = request.elements[0]
    chart = request.partition_key

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
    return LintResult.create(request, process_result)


def rules():
    return [*collect_rules(), *tool.rules(), *HelmLintRequest.rules()]
