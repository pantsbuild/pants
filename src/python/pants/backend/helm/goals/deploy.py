# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.docker.goals.package_image import DockerPackageFieldSet
from pants.backend.helm.dependency_inference import deployment
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.subsystems.post_renderer import setup_post_renderer_launcher
from pants.backend.helm.target_types import (
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
    HelmDeploymentTimeoutField,
)
from pants.backend.helm.util_rules import post_renderer
from pants.backend.helm.util_rules.post_renderer import HelmDeploymentPostRendererRequest
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentCmd,
    HelmDeploymentRequest,
    materialize_deployment_process_wrapper_into_interactive_process,
)
from pants.core.goals.deploy import DeployFieldSet, DeployProcess, DeploySubsystem
from pants.engine.internals.graph import resolve_targets
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import DependenciesRequest
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
    field_set: DeployHelmDeploymentFieldSet,
    helm_subsystem: HelmSubsystem,
    deploy_subsystem: DeploySubsystem,
) -> DeployProcess:
    dry_run_args = ["--dry-run"] if deploy_subsystem.dry_run else []
    passthrough_args = helm_subsystem.valid_args(
        extra_help=softwrap(
            f"""
            Most invalid arguments have equivalent fields in the `{HelmDeploymentTarget.alias}` target.
            Usage of fields is encouraged over passthrough arguments as that enables repeatable deployments.

            Please run `{bin_name()} help {HelmDeploymentTarget.alias}` for more information.

            To use `--dry-run`, run `{bin_name()} experimental-deploy --dry-run ::`.
            """
        )
    )

    target_dependencies, post_renderer = await concurrently(
        resolve_targets(**implicitly(DependenciesRequest(field_set.dependencies))),
        setup_post_renderer_launcher(**implicitly(HelmDeploymentPostRendererRequest(field_set))),
    )

    publish_targets = [
        tgt for tgt in target_dependencies if DockerPackageFieldSet.is_applicable(tgt)
    ]

    interactive_process = await materialize_deployment_process_wrapper_into_interactive_process(
        **implicitly(
            HelmDeploymentRequest(
                cmd=HelmDeploymentCmd.UPGRADE,
                field_set=field_set,
                extra_argv=[
                    "--install",
                    *(
                        ("--timeout", f"{field_set.timeout.value}s")
                        if field_set.timeout.value
                        else ()
                    ),
                    *passthrough_args,
                    *dry_run_args,
                ],
                post_renderer=post_renderer,
                description=f"Running Helm deployment: {field_set.address}",
            )
        )
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
