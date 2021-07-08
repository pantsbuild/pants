# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import os
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict

from pants.backend.terraform.lint.fmt import TerraformFmtRequest
from pants.backend.terraform.target_types import TerraformSources
from pants.backend.terraform.tool import TerraformTool
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class TfFmtSubsystem(Subsystem):
    options_scope = "terraform-fmt"
    help = """Terraform fmt options."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use `terraform fmt` when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`."
            ),
        )


@dataclass(frozen=True)
class TffmtFieldSet(FieldSet):
    required_fields = (TerraformSources,)

    sources: TerraformSources


class TffmtRequest(TerraformFmtRequest):
    field_set_type = TffmtFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: TffmtRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    directory_to_process: Dict[str, Process]
    original_digest: Digest


@rule(level=LogLevel.DEBUG)
async def setup_terraform_fmt(setup_request: SetupRequest, terraform: TerraformTool) -> Setup:
    download_terraform_request = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        terraform.get_request(Platform.current),
    )

    source_files_request = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets),
    )

    downloaded_terraform, source_files = await MultiGet(
        download_terraform_request, source_files_request
    )

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    input_digest = await Get(
        Digest,
        MergeDigests((source_files_snapshot.digest, downloaded_terraform.digest)),
    )

    # `terraform fmt` operates on a directory-by-directory basis. First determine the directories in
    # the snapshot. This does not use `source_files_snapshot.dirs` because that will be empty if the files
    # are in a single directory.
    directories = defaultdict(list)
    for file in source_files.snapshot.files:
        directory = os.path.dirname(file)
        if directory == "":
            directory = "."
        directories[directory].append(file)

    # Then create a process for each directory.
    directory_to_process = {}
    for directory, files_in_directory in directories.items():
        args = [
            "./terraform",
            "fmt",
        ]
        if setup_request.check_only:
            args.append("-check")
        args.append(directory)

        process = Process(
            argv=args,
            input_digest=input_digest,
            output_files=files_in_directory,
            description=f"Run `terraform fmt` on {pluralize(len(files_in_directory), 'file')}.",
            level=LogLevel.DEBUG,
        )

        directory_to_process[directory] = process

    return Setup(
        directory_to_process=directory_to_process, original_digest=source_files_snapshot.digest
    )


@rule(desc="Format with `terraform fmt`")
async def tffmt_fmt(request: TffmtRequest, tffmt: TfFmtSubsystem) -> FmtResult:
    if tffmt.options.skip:
        return FmtResult.skip(formatter_name="tffmt")
    setup = await Get(Setup, SetupRequest(request, check_only=False))
    results = await MultiGet(
        Get(ProcessResult, Process, process) for process in setup.directory_to_process.values()
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
        formatter_name="tffmt",
    )
    return fmt_result


@rule(desc="Lint with `terraform fmt`", level=LogLevel.DEBUG)
async def tffmt_lint(request: TffmtRequest, tffmt: TfFmtSubsystem) -> LintResults:
    if tffmt.options.skip:
        return LintResults([], linter_name="tffmt")
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    results = await MultiGet(
        Get(FallibleProcessResult, Process, process)
        for directory, process in setup.directory_to_process.items()
    )
    lint_results = [LintResult.from_fallible_process_result(result) for result in results]
    return LintResults(lint_results, linter_name="tffmt")


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        UnionRule(TerraformFmtRequest, TffmtRequest),
    ]
