# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.shell.lint.shell_fmt import ShellFmtRequest
from pants.backend.shell.lint.shfmt.skip_field import SkipShfmtField
from pants.backend.shell.lint.shfmt.subsystem import Shfmt
from pants.backend.shell.target_types import ShellSourceField
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class ShfmtFieldSet(FieldSet):
    required_fields = (ShellSourceField,)

    sources: ShellSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipShfmtField).value


class ShfmtRequest(ShellFmtRequest, LintRequest):
    field_set_type = ShfmtFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: ShfmtRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


@rule(level=LogLevel.DEBUG)
async def setup_shfmt(setup_request: SetupRequest, shfmt: Shfmt) -> Setup:
    download_shfmt_get = Get(
        DownloadedExternalTool, ExternalToolRequest, shfmt.get_request(Platform.current)
    )
    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets),
    )
    downloaded_shfmt, source_files = await MultiGet(download_shfmt_get, source_files_get)

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    config_files = await Get(
        ConfigFiles, ConfigFilesRequest, shfmt.config_request(source_files_snapshot.dirs)
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (source_files_snapshot.digest, downloaded_shfmt.digest, config_files.snapshot.digest)
        ),
    )

    argv = [
        downloaded_shfmt.exe,
        # If linting, use `-d` to error with a diff. Else, write the change with `-w` and list
        # what was changed with `-l`.
        *(["-d"] if setup_request.check_only else ["-l", "-w"]),
        *shfmt.args,
        *source_files_snapshot.files,
    ]
    process = Process(
        argv=argv,
        input_digest=input_digest,
        output_files=source_files_snapshot.files,
        description=f"Run shfmt on {pluralize(len(setup_request.request.field_sets), 'file')}.",
        level=LogLevel.DEBUG,
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with shfmt", level=LogLevel.DEBUG)
async def shfmt_fmt(request: ShfmtRequest, shfmt: Shfmt) -> FmtResult:
    if shfmt.skip:
        return FmtResult.skip(formatter_name="shfmt")
    setup = await Get(Setup, SetupRequest(request, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result, original_digest=setup.original_digest, formatter_name="shfmt"
    )


@rule(desc="Lint with shfmt", level=LogLevel.DEBUG)
async def shfmt_lint(request: ShfmtRequest, shfmt: Shfmt) -> LintResults:
    if shfmt.skip:
        return LintResults([], linter_name="shfmt")
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return LintResults([LintResult.from_fallible_process_result(result)], linter_name="shfmt")


def rules():
    return [
        *collect_rules(),
        UnionRule(ShellFmtRequest, ShfmtRequest),
        UnionRule(LintRequest, ShfmtRequest),
    ]
