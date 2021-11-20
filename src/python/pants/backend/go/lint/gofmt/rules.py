# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os.path
from dataclasses import dataclass

from pants.backend.go.lint.fmt import GoLangFmtRequest
from pants.backend.go.lint.gofmt.skip_field import SkipGofmtField
from pants.backend.go.lint.gofmt.subsystem import GofmtSubsystem
from pants.backend.go.subsystems import golang
from pants.backend.go.subsystems.golang import GoRoot
from pants.backend.go.target_types import GoPackageSourcesField
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class GofmtFieldSet(FieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGofmtField).value


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
async def setup_gofmt(setup_request: SetupRequest, goroot: GoRoot) -> Setup:
    source_files = await Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets),
    )
    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    argv = (
        os.path.join(goroot.path, "bin/gofmt"),
        "-l" if setup_request.check_only else "-w",
        *source_files_snapshot.files,
    )
    process = Process(
        argv=argv,
        input_digest=source_files_snapshot.digest,
        output_files=source_files_snapshot.files,
        description=f"Run gofmt on {pluralize(len(source_files_snapshot.files), 'file')}.",
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
        *golang.rules(),
        UnionRule(GoLangFmtRequest, GofmtRequest),
        UnionRule(LintRequest, GofmtRequest),
    ]
