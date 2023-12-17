# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Union

from pants.backend.terraform.dependencies import TerraformInitRequest, TerraformInitResponse
from pants.backend.terraform.target_types import (
    TerraformBackendConfigField,
    TerraformDeploymentFieldSet,
    TerraformDeploymentTarget,
    TerraformFieldSet,
    TerraformModuleTarget,
    TerraformRootModuleField,
)
from pants.backend.terraform.tool import TerraformProcess
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import BoolField, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import pluralize


class TerraformValidateSubsystem(Subsystem):
    options_scope = "terraform-validate"
    name = "`terraform validate`"
    help = """Terraform validate options."""

    skip = SkipOption("check")


class SkipTerraformValidateField(BoolField):
    alias = "skip_terraform_validate"
    default = False
    help = "If true, don't run `terraform validate` on this target's code. If this target is a module, `terraform validate might still be run on a `terraform_deployment that references this module."


@dataclass(frozen=True)
class TerraformValidateFieldSet(TerraformFieldSet):
    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTerraformValidateField).value


class TerraformCheckRequest(CheckRequest):
    field_set_type = TerraformValidateFieldSet
    tool_name = TerraformValidateSubsystem.options_scope


def terraform_fieldset_to_init_request(
    terraform_fieldset: Union[TerraformDeploymentFieldSet, TerraformFieldSet]
) -> TerraformInitRequest:
    if isinstance(terraform_fieldset, TerraformDeploymentFieldSet):
        deployment = terraform_fieldset
        return TerraformInitRequest(
            deployment.root_module, deployment.backend_config, deployment.dependencies
        )
    if isinstance(terraform_fieldset, TerraformFieldSet):
        module = terraform_fieldset
        return TerraformInitRequest(
            TerraformRootModuleField(module.address.spec, module.address),
            TerraformBackendConfigField(None, module.address),
            module.dependencies,
        )


@rule
async def terraform_check(
    request: TerraformCheckRequest, subsystem: TerraformValidateSubsystem
) -> CheckResults:
    if subsystem.skip:
        return CheckResults([], checker_name=request.tool_name)

    initialised_terraforms = await MultiGet(
        Get(
            TerraformInitResponse,
            TerraformInitRequest,
            terraform_fieldset_to_init_request(deployment),
        )
        for deployment in request.field_sets
    )

    results = await MultiGet(
        Get(
            FallibleProcessResult,
            TerraformProcess(
                args=("validate",),
                input_digest=deployment.sources_and_deps,
                output_files=tuple(deployment.terraform_files),
                description=f"Run `terraform fmt` on {pluralize(len(deployment.terraform_files), 'file')}.",
                chdir=deployment.chdir,
            ),
        )
        for deployment in initialised_terraforms
    )

    check_results = []
    for deployment, result, field_set in zip(initialised_terraforms, results, request.field_sets):
        check_results.append(
            CheckResult.from_fallible_process_result(
                result, partition_description=f"`terraform validate` on `{field_set.address}`"
            )
        )

    return CheckResults(check_results, checker_name=request.tool_name)


def rules():
    return (
        *collect_rules(),
        TerraformDeploymentTarget.register_plugin_field(SkipTerraformValidateField),
        TerraformModuleTarget.register_plugin_field(SkipTerraformValidateField),
        UnionRule(CheckRequest, TerraformCheckRequest),
    )
