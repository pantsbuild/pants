# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.terraform.dependencies import TerraformInitRequest, TerraformInitResponse
from pants.backend.terraform.target_types import (
    TerraformDeploymentFieldSet,
    TerraformVarFileSourceField,
    to_address_input,
)
from pants.backend.terraform.tool import TerraformProcess, TerraformTool
from pants.backend.terraform.utils import terraform_arg, terraform_relpath
from pants.core.goals.deploy import DeployFieldSet, DeployProcess
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import (
    EMPTY_SNAPSHOT,
    Address,
    AddressInput,
    Digest,
    MergeDigests,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import InteractiveProcess, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Targets
from pants.engine.unions import UnionRule
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
    request: TerraformDeploymentRequest, terraform_subsystem: TerraformTool
) -> InteractiveProcess:
    initialised_terraform = await Get(
        TerraformInitResponse,
        TerraformInitRequest(
            request.field_set.root_module,
            request.field_set.backend_config,
            request.field_set.dependencies,
            initialise_backend=True,
        ),
    )

    args = ["apply"]

    if request.field_set.var_files.value:
        vars_addresses = await MultiGet(
            Get(Address, AddressInput, to_address_input(x, request.field_set.var_files))
            for x in request.field_set.var_files.value
        )
        vars_targets = await Get(Targets, Addresses(vars_addresses))
        var_files = await Get(
            SourceFiles,
            SourceFilesRequest([x.get(TerraformVarFileSourceField) for x in vars_targets]),
        )
    else:
        var_files = SourceFiles(EMPTY_SNAPSHOT, ())
    for var_file in var_files.files:
        args.append(
            terraform_arg("-var-file", terraform_relpath(initialised_terraform.chdir, var_file))
        )

    with_vars = await Get(
        Digest, MergeDigests([var_files.snapshot.digest, initialised_terraform.sources_and_deps])
    )

    if terraform_subsystem.args:
        args.extend(terraform_subsystem.args)

    process = await Get(
        Process,
        TerraformProcess(
            args=tuple(args),
            input_digest=with_vars,
            description="Terraform apply",
            chdir=initialised_terraform.chdir,
        ),
    )
    return InteractiveProcess.from_process(process)


@rule(desc="Run Terraform deploy process", level=LogLevel.DEBUG)
async def run_terraform_deploy(field_set: DeployTerraformFieldSet) -> DeployProcess:
    interactive_process = await Get(
        InteractiveProcess, TerraformDeploymentRequest(field_set=field_set)
    )

    return DeployProcess(
        name=field_set.address.spec,
        process=interactive_process,
    )


def rules():
    return [*collect_rules(), UnionRule(DeployFieldSet, DeployTerraformFieldSet)]
