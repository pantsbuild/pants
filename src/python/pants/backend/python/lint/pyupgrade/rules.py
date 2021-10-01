# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.lint.python_fmt import PythonFmtRequest
from pants.backend.python.lint.pyupgrade.skip_field import SkipPyUpgradeField
from pants.backend.python.lint.pyupgrade.subsystem import PyUpgrade
from pants.backend.python.target_types import PythonSources
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PyUpgradeFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPyUpgradeField).value


class PyUpgradeRequest(PythonFmtRequest, LintRequest):
    field_set_type = PyUpgradeFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: PyUpgradeRequest


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


def generate_argv(source_files: SourceFiles, pyupgrade: PyUpgrade) -> tuple[str, ...]:
    args = [*pyupgrade.args]
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def setup_pyupgrade(setup_request: SetupRequest, pyupgrade: PyUpgrade) -> Setup:
    request = setup_request.request
    pyupgrade_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="pyupgrade.pex",
            internal_only=True,
            requirements=pyupgrade.pex_requirements(),
            interpreter_constraints=pyupgrade.interpreter_constraints,
            main=pyupgrade.main,
        ),
    )
    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in request.field_sets),
    )
    source_files, pyupgrade_pex = await MultiGet(source_files_get, pyupgrade_pex_get)

    source_files_snapshot = (
        source_files.snapshot
        if request.prior_formatter_result is None
        else request.prior_formatter_result
    )

    input_digest = await Get(Digest, MergeDigests((source_files_snapshot.digest,)))

    process = await Get(
        Process,
        VenvPexProcess(
            pyupgrade_pex,
            argv=generate_argv(source_files, pyupgrade),
            input_digest=input_digest,
            output_files=source_files_snapshot.files,
            description=f"Run pyupgrade on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with pyupgrade", level=LogLevel.DEBUG)
async def pyupgrade_fmt(request: PyUpgradeRequest, pyupgrade: PyUpgrade) -> FmtResult:
    if pyupgrade.skip:
        return FmtResult.skip(formatter_name="pyupgrade")
    setup = await Get(Setup, SetupRequest(request))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return FmtResult(
        input=setup.original_digest,
        output=result.output_digest,
        stdout=FmtResult.prep_output(result.stdout),
        stderr=FmtResult.prep_output(result.stderr),
        formatter_name="pyupgrade",
    )


@rule(desc="Lint with pyupgrade", level=LogLevel.DEBUG)
async def pyupgrade_lint(request: PyUpgradeRequest, pyupgrade: PyUpgrade) -> LintResults:
    if pyupgrade.skip:
        return LintResults([], linter_name="pyupgrade")
    setup = await Get(Setup, SetupRequest(request))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return LintResults(
        [LintResult.from_fallible_process_result(result)],
        linter_name="pyupgrade",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PythonFmtRequest, PyUpgradeRequest),
        UnionRule(LintRequest, PyUpgradeRequest),
        *pex.rules(),
    ]
