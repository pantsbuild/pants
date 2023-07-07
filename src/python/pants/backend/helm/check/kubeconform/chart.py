# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.helm.check.kubeconform import common, extra_fields
from pants.backend.helm.check.kubeconform.common import (
    KubeconformCheckRequest,
    RunKubeconformRequest,
)
from pants.backend.helm.check.kubeconform.extra_fields import KubeconformFieldSet
from pants.backend.helm.check.kubeconform.subsystem import KubeconformSubsystem
from pants.backend.helm.target_types import HelmChartFieldSet
from pants.backend.helm.util_rules import renderer
from pants.backend.helm.util_rules.renderer import RenderedHelmFiles, RenderHelmChartRequest
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class KubeconformChartFieldSet(HelmChartFieldSet, KubeconformFieldSet):
    pass


class KubeconformCheckChartRequest(KubeconformCheckRequest):
    field_set_type = KubeconformChartFieldSet


@rule
async def run_kubeconform_on_chart(field_set: KubeconformChartFieldSet) -> CheckResult:
    if field_set.skip.value:
        return CheckResult(
            exit_code=0, stdout="", stderr="", partition_description=field_set.address.spec
        )

    rendered_files = await Get(RenderedHelmFiles, RenderHelmChartRequest(field_set))
    return await Get(CheckResult, RunKubeconformRequest(field_set, rendered_files))


@rule
async def run_check_chart(
    request: KubeconformCheckChartRequest, kubeconfiorm: KubeconformSubsystem
) -> CheckResults:
    results = await MultiGet(
        Get(CheckResult, KubeconformChartFieldSet, field_set) for field_set in request.field_sets
    )
    return CheckResults(results, checker_name=kubeconfiorm.name)


def rules():
    return [
        *collect_rules(),
        *extra_fields.rules(),
        *renderer.rules(),
        *common.rules(),
        UnionRule(CheckRequest, KubeconformCheckChartRequest),
    ]
