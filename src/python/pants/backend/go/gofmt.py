# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from dataclasses import dataclass

from pants.backend.go.distribution import GoLangDistribution
from pants.backend.go.lint.fmt import GoLangFmtRequest
from pants.backend.go.lint.gofmt.subsystem import GofmtSubsystem
from pants.backend.go.target_types import GoSources
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
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class GofmtFieldSet(FieldSet):
    required_fields = (GoSources,)

    sources: GoSources


class GofmtRequest(GoLangFmtRequest):
    field_set_type = GofmtFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: GofmtRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


@rule(level=LogLevel.DEBUG)
async def setup_gofmt(setup_request: SetupRequest, goroot: GoLangDistribution) -> Setup:
    download_goroot_request = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        goroot.get_request(Platform.current),
    )

    source_files_request = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets),
    )

    downloaded_goroot, source_files = await MultiGet(download_goroot_request, source_files_request)

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    input_digest = await Get(
        Digest,
        MergeDigests((source_files_snapshot.digest, downloaded_goroot.digest)),
    )

    argv = [
        "./go/bin/gofmt",
        "-l" if setup_request.check_only else "-w",
        *source_files_snapshot.files,
    ]

    process = Process(
        argv=argv,
        input_digest=input_digest,
        output_files=source_files_snapshot.files,
        description=f"Run gofmt on {pluralize(len(setup_request.request.field_sets), 'file')}.",
        level=LogLevel.DEBUG,
    )

    return Setup(process=process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with gofmt")
async def gofmt_fmt(request: GofmtRequest, gofmt: GofmtSubsystem) -> FmtResult:
    if gofmt.options.skip:
        return FmtResult.skip(formatter_name="gofmt")
    setup = await Get(Setup, SetupRequest(request, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result, original_digest=setup.original_digest, formatter_name="gofmt"
    )


@rule(desc="Lint with gofmt", level=LogLevel.DEBUG)
async def gofmt_lint(request: GofmtRequest, gofmt: GofmtSubsystem) -> LintResults:
    if gofmt.options.skip:
        return LintResults([], linter_name="gofmt")
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    lint_result = LintResult.from_fallible_process_result(result)
    if lint_result.exit_code == 0 and lint_result.stdout.strip() != "":
        # Note: gofmt returns success even if it would have reformatted the files.
        # When this occurs, convert the LintResult into a failure.
        lint_result = dataclasses.replace(
            lint_result,
            exit_code=1,
            stdout=f"The following Go files require formatting:\n{lint_result.stdout}\n",
        )
    return LintResults([lint_result], linter_name="gofmt")


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        UnionRule(GoLangFmtRequest, GofmtRequest),
    ]
