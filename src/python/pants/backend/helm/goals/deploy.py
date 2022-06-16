# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.helm.dependency_inference import deployment
from pants.backend.helm.subsystems.post_renderer import PostRendererLauncherSetup
from pants.backend.helm.target_types import HelmDeploymentFieldSet, HelmDeploymentTarget
from pants.backend.helm.util_rules import post_renderer
from pants.backend.helm.util_rules.deployment import (
    HelmDeploymentRenderer,
    HelmDeploymentRendererCmd,
    SetupHelmDeploymentRenderer,
)
from pants.backend.helm.util_rules.post_renderer import PreparePostRendererRequest
from pants.backend.helm.util_rules.process import HelmProcess
from pants.core.goals.deploy import DeployFieldSet, DeployProcess, DeployProcesses, DeploySubsystem
from pants.engine.process import InteractiveProcess, InteractiveProcessRequest, Process
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployHelmDeploymentFieldSet(HelmDeploymentFieldSet, DeployFieldSet):
    pass


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
    "--set",
    "--set-string",
]


class InvalidDeploymentArgs(Exception):
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
) -> DeployProcesses:
    valid_args, invalid_args = _cleanup_passthrough_args(deploy.args)
    if invalid_args:
        raise InvalidDeploymentArgs(invalid_args)

    post_renderer = await Get(PostRendererLauncherSetup, PreparePostRendererRequest(field_set))
    renderer = await Get(
        HelmDeploymentRenderer,
        SetupHelmDeploymentRenderer(
            cmd=HelmDeploymentRendererCmd.UPGRADE,
            field_set=field_set,
            extra_argv=[
                "--install",
                *(("--create-namespace",) if field_set.create_namespace.value else ()),
                *valid_args,
            ],
            post_renderer=post_renderer,
            description=f"Deploying release {field_set.address}.",
        ),
    )

    process = await Get(Process, HelmProcess, renderer.process)
    interactive_process = await Get(InteractiveProcess, InteractiveProcessRequest(process))
    return DeployProcesses(
        [DeployProcess(name=field_set.address.spec, process=interactive_process)]
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
