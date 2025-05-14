# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.terraform.dependencies import TerraformInitRequest, prepare_terraform_invocation
from pants.backend.terraform.dependency_inference import (
    TerraformDeploymentInvocationFilesRequest,
    get_terraform_backend_and_vars,
)
from pants.backend.terraform.target_types import TerraformDeploymentFieldSet
from pants.backend.terraform.tool import (
    TerraformCommand,
    TerraformProcess,
    TerraformTool,
    setup_terraform_process,
)
from pants.backend.terraform.utils import terraform_arg, terraform_relpath
from pants.core.goals.deploy import DeployFieldSet, DeployProcess, DeploySubsystem
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.intrinsics import merge_digests
from pants.engine.process import InteractiveProcess
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import SourcesField
from pants.engine.unions import UnionRule
from pants.option.global_options import KeepSandboxes
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployTerraformFieldSet(TerraformDeploymentFieldSet, DeployFieldSet):
    pass


@dataclass(frozen=True)
class TerraformDeploymentRequest(EngineAwareParameter):
    field_set: TerraformDeploymentFieldSet


@rule
async def prepare_terraform_deployment(
    request: TerraformDeploymentRequest,
    terraform_subsystem: TerraformTool,
    deploy_subsystem: DeploySubsystem,
    keep_sandboxes: KeepSandboxes,
) -> InteractiveProcess:
    deployment = await prepare_terraform_invocation(
        TerraformInitRequest(
            request.field_set.root_module,
            request.field_set.dependencies,
            initialise_backend=True,
        )
    )

    terraform_command = "plan" if deploy_subsystem.dry_run else "apply"
    args = [terraform_command]

    invocation_files = await get_terraform_backend_and_vars(
        TerraformDeploymentInvocationFilesRequest(
            request.field_set.dependencies.address, request.field_set.dependencies
        )
    )
    var_files = await determine_source_files(
        SourceFilesRequest(e.get(SourcesField) for e in invocation_files.vars_files)
    )
    for var_file in var_files.files:
        args.append(terraform_arg("-var-file", terraform_relpath(deployment.chdir, var_file)))

    with_vars = await merge_digests(
        MergeDigests(
            [
                var_files.snapshot.digest,
                deployment.terraform_sources.snapshot.digest,
                deployment.dependencies_files.snapshot.digest,
            ]
        )
    )

    if terraform_subsystem.args:
        args.extend(terraform_subsystem.args)

    process = await setup_terraform_process(
        TerraformProcess(
            cmds=(
                deployment.init_cmd.to_args(),
                TerraformCommand(tuple(args)),
            ),
            input_digest=with_vars,
            description=f"Terraform {terraform_command}",
            chdir=deployment.chdir,
        ),
        **implicitly(),
    )
    return InteractiveProcess.from_process(process, keep_sandboxes=keep_sandboxes)


@rule(desc="Run Terraform deploy process", level=LogLevel.DEBUG)
async def run_terraform_deploy(field_set: DeployTerraformFieldSet) -> DeployProcess:
    interactive_process = await prepare_terraform_deployment(
        TerraformDeploymentRequest(field_set=field_set), **implicitly()
    )

    return DeployProcess(
        name=field_set.address.spec,
        process=interactive_process,
    )


def rules():
    return [*collect_rules(), UnionRule(DeployFieldSet, DeployTerraformFieldSet)]
