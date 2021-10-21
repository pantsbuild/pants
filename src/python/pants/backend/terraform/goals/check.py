# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast

from pants.backend.terraform.style import StyleSetup, StyleSetupRequest
from pants.backend.terraform.target_types import TerraformFieldSet
from pants.backend.terraform.tool import TerraformProcess
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem


class TerraformValidateSubsystem(Subsystem):
    options_scope = "terraform-validate"
    help = """Terraform validate options."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't run `terraform validate` when running `{register.bootstrap.pants_bin_name} check`."
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)


class TerraformCheckRequest(CheckRequest):
    field_set_type = TerraformFieldSet


@rule
async def terraform_check(
    request: TerraformCheckRequest, subsystem: TerraformValidateSubsystem
) -> CheckResults:
    if subsystem.options.skip:
        return CheckResults([], checker_name="terraform validate")

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

    return CheckResults(check_results, checker_name="terraform validate")


def rules():
    return (
        *collect_rules(),
        UnionRule(CheckRequest, TerraformCheckRequest),
    )
