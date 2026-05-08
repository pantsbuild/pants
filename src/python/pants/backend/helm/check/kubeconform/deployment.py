# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.helm.check.kubeconform import common, extra_fields
from pants.backend.helm.check.kubeconform.common import (
    KubeconformCheckRequest,
    RunKubeconformRequest,
    run_kubeconform,
)
from pants.backend.helm.check.kubeconform.extra_fields import KubeconformFieldSet
from pants.backend.helm.check.kubeconform.subsystem import KubeconformSubsystem
from pants.backend.helm.dependency_inference import deployment as infer_deployment
from pants.backend.helm.subsystems.post_renderer import setup_post_renderer_launcher
from pants.backend.helm.target_types import HelmDeploymentFieldSet
from pants.backend.helm.util_rules import post_renderer, renderer
from pants.backend.helm.util_rules.post_renderer import HelmDeploymentPostRendererRequest
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentCmd,
    HelmDeploymentRequest,
    run_renderer,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KubeconformDeploymentFieldSet(HelmDeploymentFieldSet, KubeconformFieldSet):
    pass


class KubeconformCheckDeploymentRequest(KubeconformCheckRequest):
    field_set_type = KubeconformDeploymentFieldSet


@rule
async def run_kubeconform_on_deployment(
    field_set: KubeconformDeploymentFieldSet,
) -> CheckResult:
    if field_set.skip.value:
        return CheckResult(
            exit_code=0, stdout="", stderr="", partition_description=field_set.address.spec
        )

    post_renderer = await setup_post_renderer_launcher(
        **implicitly(HelmDeploymentPostRendererRequest(field_set))
    )
    rendered_files = await run_renderer(
        **implicitly(
            HelmDeploymentRequest(
                field_set,
                cmd=HelmDeploymentCmd.RENDER,
                post_renderer=post_renderer,
                description=f"Evaluating Helm deployment files for {field_set.address}",
            )
        )
    )

    return await run_kubeconform(RunKubeconformRequest(field_set, rendered_files), **implicitly())


@rule
async def run_check_deployment(
    request: KubeconformCheckDeploymentRequest,
    kubeconform: KubeconformSubsystem,
) -> CheckResults:
    check_results = await concurrently(
        run_kubeconform_on_deployment(field_set) for field_set in request.field_sets
    )
    return CheckResults(check_results, checker_name=kubeconform.name)


def rules():
    return [
        *collect_rules(),
        *extra_fields.rules(),
        *infer_deployment.rules(),
        *post_renderer.rules(),
        *renderer.rules(),
        *common.rules(),
        UnionRule(CheckRequest, KubeconformCheckDeploymentRequest),
    ]
