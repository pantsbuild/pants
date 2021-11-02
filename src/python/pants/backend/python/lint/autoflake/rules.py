# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.autoflake.skip_field import SkipAutoflakeField
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.lint.python_fmt import PythonFmtRequest
from pants.backend.python.target_types import InterpreterConstraintsField, PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class AutoflakeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipAutoflakeField).value


class AutoflakeRequest(PythonFmtRequest, LintRequest):
    field_set_type = AutoflakeFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: AutoflakeRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


def generate_argv(
    source_files: SourceFiles, autoflake: Autoflake, *, check_only: bool
) -> Tuple[str, ...]:
    args = []
    if check_only:
        args.append("--check")
    else:
        args.append("--in-place")
    args.append("--remove-all-unused-imports")
    args.extend(autoflake.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def setup_autoflake(setup_request: SetupRequest, autoflake: Autoflake) -> Setup:
    autoflake_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="autoflake.pex",
            internal_only=True,
            requirements=autoflake.pex_requirements(),
            interpreter_constraints=autoflake.interpreter_constraints,
            main=autoflake.main,
        ),
    )

    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.source for field_set in setup_request.request.field_sets),
    )

    source_files, autoflake_pex = await MultiGet(source_files_get, autoflake_pex_get)
    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    process = await Get(
        Process,
        VenvPexProcess(
            autoflake_pex,
            argv=generate_argv(source_files, autoflake, check_only=setup_request.check_only),
            input_digest=source_files_snapshot.digest,
            output_files=source_files_snapshot.files,
            description=f"Run Autoflake on {pluralize(len(setup_request.request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with Autoflake", level=LogLevel.DEBUG)
async def autoflake_fmt(field_sets: AutoflakeRequest, autoflake: Autoflake) -> FmtResult:
    if autoflake.skip:
        return FmtResult.skip(formatter_name="autoflake")
    setup = await Get(Setup, SetupRequest(field_sets, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result,
        original_digest=setup.original_digest,
        formatter_name="autoflake",
        strip_chroot_path=True,
    )


@rule(desc="Lint with autoflake", level=LogLevel.DEBUG)
async def autoflake_lint(request: AutoflakeRequest, autoflake: Autoflake) -> LintResults:
    if autoflake.skip:
        return LintResults([], linter_name="autoflake")
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)

    def strip_check_result(output: str) -> str:
        return "\n".join(line for line in output.splitlines() if line != "No issues detected!")

    return LintResults(
        [
            LintResult(
                result.exit_code,
                strip_check_result(result.stdout.decode()),
                result.stderr.decode(),
            )
        ],
        linter_name="autoflake",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PythonFmtRequest, AutoflakeRequest),
        UnionRule(LintRequest, AutoflakeRequest),
        *pex.rules(),
    ]
