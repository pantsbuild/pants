# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.helm.target_types import HelmDeploymentFieldSet, HelmDeploymentTarget
from pants.backend.helm.util_rules import deployment
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.process import HelmEvaluateProcess
from pants.core.goals.deploy import DeployFieldSet, DeployProcess, DeployProcesses, DeploySubsystem
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address
from pants.engine.process import InteractiveProcess, InteractiveProcessRequest, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import WrappedTarget
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
                Usage of fields is encourage over passthrough arguments as that enables repeatable deployments.

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

    deployment_tgt = await Get(WrappedTarget, Address, field_set.address)
    chart, values_files = await MultiGet(
        Get(
            HelmChart, HelmDeploymentFieldSet, HelmDeploymentFieldSet.create(deployment_tgt.target)
        ),
        Get(
            StrippedSourceFiles,
            SourceFilesRequest([field_set.sources]),
        ),
    )

    # input_digest = await Get(
    #     Digest, MergeDigests([chart.snapshot.digest, values_files.snapshot.digest])
    # )

    release_name = field_set.release_name.value or field_set.address.target_name

    helm_cmd = await Get(
        Process,
        HelmEvaluateProcess(
            cmd="upgrade",
            release_name=release_name,
            chart_path=chart.path,
            chart_digest=chart.snapshot.digest,
            description=field_set.description.value,
            namespace=field_set.namespace.value,
            skip_crds=field_set.skip_crds.value,
            no_hooks=field_set.no_hooks.value,
            values_snapshot=values_files.snapshot,
            values=field_set.values.value,
            extra_argv=[
                "--install",
                *(("--create-namespace",) if field_set.create_namespace.value else ()),
                *valid_args,
            ],
            message=(
                f"Deploying release '{release_name}' using chart "
                f"{chart.address} and values from {field_set.address}."
            ),
        ),
    )

    process = await Get(InteractiveProcess, InteractiveProcessRequest(helm_cmd))
    return DeployProcesses([DeployProcess(name=field_set.address.spec, process=process)])


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
        UnionRule(DeployFieldSet, DeployHelmDeploymentFieldSet),
    ]
