# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.terraform.style import StyleSetup, StyleSetupRequest
from pants.backend.terraform.target_types import TerraformFieldSet
from pants.backend.terraform.tool import TerraformProcess
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem


class TerraformValidateSubsystem(Subsystem):
    options_scope = "terraform-validate"
    name = "`terraform validate`"
    help = """Terraform validate options."""

    skip = SkipOption("check")


class TerraformCheckRequest(CheckRequest):
    field_set_type = TerraformFieldSet
    name = TerraformValidateSubsystem.options_scope


@rule
async def terraform_check(
    request: TerraformCheckRequest, subsystem: TerraformValidateSubsystem
) -> CheckResults:
    if subsystem.skip:
        return CheckResults([], checker_name=request.name)

    setup = await Get(StyleSetup, StyleSetupRequest(request, ("validate",)))
    results = await MultiGet(
        Get(FallibleProcessResult, TerraformProcess, process)
        for _, (process, _) in setup.directory_to_process.items()
    )

    check_results = []
    for directory, result in zip(setup.directory_to_process.keys(), results):
        check_results.append(
            CheckResult.from_fallible_process_result(
                result, partition_description=f"`terraform validate` on `{directory}`"
            )
        )

    return CheckResults(check_results, checker_name=request.name)


def rules():
    return (
        *collect_rules(),
        UnionRule(CheckRequest, TerraformCheckRequest),
    )
