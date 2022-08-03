# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.docker.goals.package_image import DockerFieldSet
from pants.backend.helm.dependency_inference import deployment
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.subsystems.post_renderer import HelmPostRenderer
from pants.backend.helm.target_types import (
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
    HelmDeploymentTimeoutField,
)
from pants.backend.helm.util_rules import post_renderer
from pants.backend.helm.util_rules.post_renderer import HelmDeploymentPostRendererRequest
from pants.backend.helm.util_rules.renderer import HelmDeploymentCmd, HelmDeploymentRequest
from pants.core.goals.deploy import DeployFieldSet, DeployProcess
from pants.engine.process import InteractiveProcess
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, Targets
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployHelmDeploymentFieldSet(HelmDeploymentFieldSet, DeployFieldSet):

    timeout: HelmDeploymentTimeoutField


@rule(desc="Run Helm deploy process", level=LogLevel.DEBUG)
async def run_helm_deploy(
    field_set: DeployHelmDeploymentFieldSet, helm_subsystem: HelmSubsystem
) -> DeployProcess:
    passthrough_args = helm_subsystem.valid_args(
        extra_help=softwrap(
            f"""
            Most invalid arguments have equivalent fields in the `{HelmDeploymentTarget.alias}` target.
            Usage of fields is encouraged over passthrough arguments as that enables repeatable deployments.

            Please run `{bin_name()} help {HelmDeploymentTarget.alias}` for more information.
            """
        )
    )

    target_dependencies, post_renderer = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies)),
        Get(HelmPostRenderer, HelmDeploymentPostRendererRequest(field_set)),
    )

    publish_targets = [tgt for tgt in target_dependencies if DockerFieldSet.is_applicable(tgt)]

    interactive_process = await Get(
        InteractiveProcess,
        HelmDeploymentRequest(
            cmd=HelmDeploymentCmd.UPGRADE,
            field_set=field_set,
            extra_argv=[
                "--install",
                *(("--timeout", f"{field_set.timeout.value}s") if field_set.timeout.value else ()),
                *passthrough_args,
            ],
            post_renderer=post_renderer,
            description=f"Deploying {field_set.address}",
        ),
    )

    return DeployProcess(
        name=field_set.address.spec,
        publish_dependencies=tuple(publish_targets),
        process=interactive_process,
    )


def rules():
    return [
        *collect_rules(),
        *deployment.rules(),
        *post_renderer.rules(),
        UnionRule(DeployFieldSet, DeployHelmDeploymentFieldSet),
    ]
