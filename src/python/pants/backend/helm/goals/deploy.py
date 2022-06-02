# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain
from typing import Iterable

from pants.backend.helm.target_types import HelmDeploymentFieldSet, HelmDeploymentTarget
from pants.backend.helm.util_rules import deployment
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.render import sort_value_file_names_for_rendering
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.goals.deploy import DeployFieldSet, DeployProcess, DeployProcesses, DeploySubsystem
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import InteractiveProcess, InteractiveProcessRequest, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap, bullet_list

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

                {bullet_list([+_VALID_PASSTHROUGH_FLAGS, *_VALID_PASSTHROUGH_OPTS])}

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

    input_digest = await Get(
        Digest, MergeDigests([chart.snapshot.digest, values_files.snapshot.digest])
    )

    release_name = field_set.release_name.value or field_set.address.target_name
    sorted_value_files = sort_value_file_names_for_rendering(values_files.snapshot.files)

    helm_cmd = await Get(
        Process,
        HelmProcess(
            argv=[
                "upgrade",
                release_name,
                chart.path,
                "--install",
                *(
                    ("--description", f'"{field_set.description.value}"')
                    if field_set.description.value
                    else ()
                ),
                *(("--namespace", field_set.namespace.value) if field_set.namespace.value else ()),
                *(("--create-namespace",) if field_set.create_namespace.value else ()),
                *(("--skip-crds",) if field_set.skip_crds.value else ()),
                *(("--no-hooks",) if field_set.no_hooks.value else ()),
                *(("--values", ",".join(sorted_value_files)) if sorted_value_files else ()),
                *chain.from_iterable(
                    [
                        ("--set", f"{key}={value}")
                        for key, value in (field_set.values.value or {}).items()
                    ]
                ),
                *valid_args,
            ],
            input_digest=input_digest,
            description=(
                f"Deploying release '{release_name}' using chart "
                f"{chart.address} and values from {field_set.address}."
            ),
            level=LogLevel.DEBUG,
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
