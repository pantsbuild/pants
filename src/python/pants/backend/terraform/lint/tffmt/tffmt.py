# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import textwrap

from pants.backend.terraform.style import StyleSetup, StyleSetupRequest
from pants.backend.terraform.target_types import TerraformFieldSet
from pants.backend.terraform.tool import TerraformProcess
from pants.backend.terraform.tool import rules as tool_rules
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules import external_tool
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class TfFmtSubsystem(Subsystem):
    options_scope = "terraform-fmt"
    help = "Terraform fmt options."

    skip = BoolOption(
        "--skip",
        default=False,
        help=f"Don't use `terraform fmt` when running `{bin_name()} fmt` and `{bin_name()} lint`.",
    )


class TffmtRequest(FmtRequest):
    field_set_type = TerraformFieldSet
    name = TfFmtSubsystem.options_scope


@rule(desc="Format with `terraform fmt`")
async def tffmt_fmt(request: TffmtRequest, tffmt: TfFmtSubsystem) -> FmtResult:
    if tffmt.skip:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(StyleSetup, StyleSetupRequest(request, ("fmt",)))
    results = await MultiGet(
        Get(ProcessResult, TerraformProcess, process)
        for _, (process, _) in setup.directory_to_process.items()
    )

    def format(directory, output):
        if len(output.strip()) == 0:
            return ""

        return textwrap.dedent(
            f"""\
        Output from `terraform fmt` on files in {directory}:
        {output.decode("utf-8")}

        """
        )

    stdout_content = ""
    stderr_content = ""
    for directory, result in zip(setup.directory_to_process.keys(), results):
        stdout_content += format(directory, result.stdout)
        stderr_content += format(directory, result.stderr)

    # Merge all of the outputs into a single output.
    output_digest = await Get(Digest, MergeDigests(r.output_digest for r in results))

    fmt_result = FmtResult(
        input=setup.original_digest,
        output=output_digest,
        stdout=stdout_content,
        stderr=stderr_content,
        formatter_name=request.name,
    )
    return fmt_result


@rule(desc="Lint with `terraform fmt`", level=LogLevel.DEBUG)
async def tffmt_lint(request: TffmtRequest, tffmt: TfFmtSubsystem) -> LintResults:
    if tffmt.skip:
        return LintResults([], linter_name=request.name)
    setup = await Get(StyleSetup, StyleSetupRequest(request, ("fmt", "-check")))
    results = await MultiGet(
        Get(FallibleProcessResult, TerraformProcess, process)
        for _, (process, _) in setup.directory_to_process.items()
    )
    lint_results = [LintResult.from_fallible_process_result(result) for result in results]
    return LintResults(lint_results, linter_name=request.name)


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        *tool_rules(),
        UnionRule(LintTargetsRequest, TffmtRequest),
        UnionRule(FmtRequest, TffmtRequest),
    ]
