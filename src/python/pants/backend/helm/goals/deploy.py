# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.docker.goals.package_image import DockerFieldSet
from pants.backend.helm.dependency_inference import deployment
from pants.backend.helm.subsystems.post_renderer import HelmPostRenderer
from pants.backend.helm.target_types import (
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
    HelmDeploymentTimeoutField,
)
from pants.backend.helm.util_rules import post_renderer
from pants.backend.helm.util_rules.post_renderer import HelmDeploymentPostRendererRequest
from pants.backend.helm.util_rules.renderer import HelmDeploymentCmd, HelmDeploymentRequest
from pants.core.goals.deploy import DeployFieldSet, DeployProcess, DeploySubsystem
from pants.engine.process import InteractiveProcess
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, Targets
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployHelmDeploymentFieldSet(HelmDeploymentFieldSet, DeployFieldSet):

    timeout: HelmDeploymentTimeoutField


_VALID_PASSTHROUGH_FLAGS = [
    "--atomic",
    "--dry-run",
    "--debug",
    "--force",
    "--replace",
    "--wait",
    "--wait-for-jobs",
]

_VALID_PASSTHROUGH_OPTS = [
    "--kubeconfig",
    "--kube-context",
    "--kube-apiserver",
    "--kube-as-group",
    "--kube-as-user",
    "--kube-ca-file",
    "--kube-token",
]


class InvalidHelmDeploymentArgs(Exception):
    def __init__(self, args: Iterable[str]) -> None:
        super().__init__(
            softwrap(
                f"""
                The following command line arguments are not valid: {' '.join(args)}.

                Only the following passthrough arguments are allowed:

                {bullet_list([*_VALID_PASSTHROUGH_FLAGS, *_VALID_PASSTHROUGH_OPTS])}

                Most invalid arguments have equivalent fields in the `{HelmDeploymentTarget.alias}` target.
                Usage of fields is encouraged over passthrough arguments as that enables repeatable deployments.

                Please run `{bin_name()} help {HelmDeploymentTarget.alias}` for more information.
                """
            )
        )


@rule(desc="Run Helm deploy process", level=LogLevel.DEBUG)
async def run_helm_deploy(
    field_set: DeployHelmDeploymentFieldSet,
    deploy: DeploySubsystem,
) -> DeployProcess:
    valid_args, invalid_args = _cleanup_passthrough_args(deploy.args)
    if invalid_args:
        raise InvalidHelmDeploymentArgs(invalid_args)

    target_dependencies, post_renderer = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies)),
        Get(HelmPostRenderer, HelmDeploymentPostRendererRequest(field_set)),
    )

    publish_targets = [tgt for tgt in target_dependencies if DockerFieldSet.is_applicable(tgt)]

    renderer = await Get(
        InteractiveProcess,
        HelmDeploymentRequest(
            cmd=HelmDeploymentCmd.UPGRADE,
            field_set=field_set,
            extra_argv=[
                "--install",
                *(("--timeout", f"{field_set.timeout.value}s") if field_set.timeout.value else ()),
                *valid_args,
            ],
            post_renderer=post_renderer,
            description=f"Deploying {field_set.address}",
        ),
    )

    return DeployProcess(
        name=field_set.address.spec, publish_dependencies=tuple(publish_targets), process=renderer
    )


def _cleanup_passthrough_args(args: Iterable[str]) -> tuple[list[str], list[str]]:
    valid_args: list[str] = []
    removed_args: list[str] = []

    skip = False
    for arg in list(args):
        if skip:
            valid_args.append(arg)
            skip = False
            continue

        if arg in _VALID_PASSTHROUGH_FLAGS:
            valid_args.append(arg)
        elif "=" in arg and arg.split("=")[0] in _VALID_PASSTHROUGH_OPTS:
            valid_args.append(arg)
        elif arg in _VALID_PASSTHROUGH_OPTS:
            valid_args.append(arg)
            skip = True
        else:
            removed_args.append(arg)

    return (valid_args, removed_args)


def rules():
    return [
        *collect_rules(),
        *deployment.rules(),
        *post_renderer.rules(),
        UnionRule(DeployFieldSet, DeployHelmDeploymentFieldSet),
    ]
