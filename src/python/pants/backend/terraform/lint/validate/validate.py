# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.terraform.target_types import TerraformSources
from pants.backend.terraform.tool import TerraformTool
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


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


@dataclass(frozen=True)
class ValidateFieldSet(FieldSet):
    required_fields = (TerraformSources,)

    sources: TerraformSources


class ValidateRequest(LintRequest):
    field_set_type = ValidateFieldSet


@rule(desc="Lint with `terraform validate`", level=LogLevel.DEBUG)
async def run_terraform_validate(
    request: ValidateRequest, terraform: TerraformTool, subsystem: TerraformValidateSubsystem
) -> LintResults:
    if subsystem.options.skip:
        return LintResults([], linter_name="terraform validate")

    download_terraform_request = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        terraform.get_request(Platform.current),
    )

    sources_request = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in request.field_sets),
    )

    downloaded_terraform, source_files = await MultiGet(download_terraform_request, sources_request)

    input_digest = await Get(
        Digest,
        MergeDigests((source_files.snapshot.digest, downloaded_terraform.digest)),
    )

    # `terraform validate` operates on a directory-by-directory basis. First determine the directories in
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
            "validate",
            directory,
        ]
        args = [arg for arg in args if arg]

        process = Process(
            argv=args,
            input_digest=input_digest,
            output_files=files_in_directory,
            description=f"Run `terraform validate` on {pluralize(len(files_in_directory), 'file')}.",
            level=LogLevel.DEBUG,
        )

        directory_to_process[directory] = process

    results = await MultiGet(
        Get(FallibleProcessResult, Process, process) for process in directory_to_process.values()
    )

    lint_results = []
    for directory, result in zip(directory_to_process.keys(), results):
        lint_result = LintResult(
            exit_code=result.exit_code,
            stdout=result.stdout.decode(),
            stderr=result.stderr.decode(),
            partition_description=f"`terraform validate` on `{directory}`",
        )
        lint_results.append(lint_result)

    return LintResults(lint_results, linter_name="terraform validate")


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        UnionRule(LintRequest, ValidateRequest),
        SubsystemRule(TerraformValidateSubsystem),
    ]
