# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.terraform.style import StyleRequest, StyleSetup, StyleSetupRequest
from pants.backend.terraform.tool import TerraformProcess
from pants.backend.terraform.tool import rules as tool_rules
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules import external_tool
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import SubsystemRule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel


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
                f"Don't use `terraform validate` when running `{register.bootstrap.pants_bin_name} lint`."
            ),
        )


class ValidateRequest(StyleRequest):
    pass


@rule(desc="Lint with `terraform validate`", level=LogLevel.DEBUG)
async def run_terraform_validate(
    request: ValidateRequest, subsystem: TerraformValidateSubsystem
) -> LintResults:
    if subsystem.options.skip:
        return LintResults([], linter_name="terraform validate")

    setup = await Get(StyleSetup, StyleSetupRequest(request, ("validate",)))
    results = await MultiGet(
        Get(FallibleProcessResult, TerraformProcess, process)
        for _, (process, _) in setup.directory_to_process.items()
    )
    lint_results = []
    for directory, result in zip(setup.directory_to_process.keys(), results):
        lint_results.append(
            LintResult.from_fallible_process_result(
                result, partition_description=f"`terraform validate` on `{directory}`"
            )
        )

    return LintResults(lint_results, linter_name="terraform validate")


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        *tool_rules(),
        UnionRule(LintRequest, ValidateRequest),
        SubsystemRule(TerraformValidateSubsystem),
    ]
