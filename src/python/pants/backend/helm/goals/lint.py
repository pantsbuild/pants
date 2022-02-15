# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.helm.subsystem import HelmSubsystem
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


@dataclass(frozen=True)
class HelmLintPartition:
    process: Process
    description: str


@dataclass(frozen=True)
class SetupHelmLintPartition:
    field_set: HelmLintFieldSet


@rule(level=LogLevel.DEBUG)
async def setup_helm_lint_partition(
    request: SetupHelmLintPartition, helm: HelmBinary
) -> HelmLintPartition:
    wrapped_target = await Get(WrappedTarget, Address, request.field_set.address)
    chart = await Get(HelmChart, HelmChartFieldSet, HelmChartFieldSet.create(wrapped_target.target))
    process = helm.lint(
        chart=chart.metadata.name,
        path=chart.path,
        chart_digest=chart.snapshot.digest,
        strict=request.field_set.lint_strict.value,
    )
    return HelmLintPartition(
        process, f"{chart.metadata.name} ({pluralize(len(chart.snapshot.files), 'file')})"
    )


@rule(desc="Lint Helm chart", level=LogLevel.DEBUG)
async def run_helm_lint(request: HelmLintRequest) -> LintResults:
    partitions = await MultiGet(
        Get(HelmLintPartition, SetupHelmLintPartition(field_set))
        for field_set in request.field_sets
    )

    process_results = await MultiGet(
        Get(FallibleProcessResult, Process, partition.process) for partition in partitions
    )
    results = [LintResult.from_fallible_process_result(r) for r in process_results]
    return LintResults(results, linter_name=request.name)


def rules():
    return [*collect_rules(), UnionRule(LintTargetsRequest, HelmLintRequest)]
