# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.helm.target_types import HelmDeploymentFieldSet
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.tool import HelmBinary, InstallOutputFormat
from pants.core.goals.install import (
    InstallFieldSet,
    InstallProcess,
    InstallProcesses,
    InstallSubsystem,
)
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address
from pants.engine.process import InteractiveProcess, InteractiveProcessRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstallHelmDeploymentFieldSet(HelmDeploymentFieldSet, InstallFieldSet):
    pass


_VALID_PASSTHROUGH_FLAGS = [
    "--atomic",
    "--dry-run",
    "--debug",
    "--force",
    "--reset-values",
    "--reuse-values",
    "--wait",
    "--wait-for-jobs",
]

_VALID_PASSTHROUGH_OPTS = ["--kubeconfig"]


@rule(desc="Run Helm install process", level=LogLevel.DEBUG)
async def run_helm_install(
    field_set: InstallHelmDeploymentFieldSet,
    install: InstallSubsystem,
    helm_binary: HelmBinary,
) -> InstallProcesses:
    valid_args, removed_args = _cleanup_passthrough_args(install.options.args)
    if removed_args:
        logger.warning(f"The following arguments are ignored: {removed_args}")

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

    helm_process = helm_binary.upgrade(
        field_set.release_name.value or field_set.address.target_name,
        path=chart.path,
        install=True,
        namespace=field_set.namespace.value,
        description=field_set.description.value,
        value_files=values_files.snapshot,
        values=field_set.values.value or FrozenDict[str, str](),
        chart_digest=chart.snapshot.digest,
        skip_crds=field_set.skip_crds.value,
        output_format=InstallOutputFormat.TABLE,
        timeout=field_set.timeout.value,
        extra_args=valid_args,
    )
    interactive_helm = await Get(InteractiveProcess, InteractiveProcessRequest(helm_process))

    process = InstallProcess(
        name=field_set.address.spec,
        process=interactive_helm,
    )
    return InstallProcesses([process])


def _cleanup_passthrough_args(args: Iterable[str]) -> tuple[list[str], list[str]]:
    valid_args: list[str] = []
    removed_args: list[str] = []

    skip = False
    for arg in list(args):
        if skip:
            valid_args.append(arg)
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
        skip = False

    return (valid_args, removed_args)


def rules():
    return [*collect_rules(), UnionRule(InstallFieldSet, InstallHelmDeploymentFieldSet)]
