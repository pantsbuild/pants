# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.python_fmt import PythonFmtRequest
from pants.backend.python.lint.yapf.skip_field import SkipYapfField
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class YapfFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipYapfField).value


class YapfRequest(PythonFmtRequest, LintRequest):
    field_set_type = YapfFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: YapfRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


def generate_argv(source_files: SourceFiles, yapf: Yapf, check_only: bool) -> Tuple[str, ...]:
    args = [*yapf.args]
    if check_only:
        # If "--diff" is passed, yapf returns zero when no changes were necessary and
        # non-zero otherwise
        args.append("--diff")
    else:
        # The "--in-place" flag makes yapf to actually reformat files
        args.append("--in-place")
    if yapf.config:
        args.extend(["--style", yapf.config])
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def setup_yapf(setup_request: SetupRequest, yapf: Yapf) -> Setup:
    yapf_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="yapf.pex",
            internal_only=True,
            requirements=yapf.pex_requirements(),
            interpreter_constraints=yapf.interpreter_constraints,
            main=yapf.main,
        ),
    )
    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.source for field_set in setup_request.request.field_sets),
    )
    source_files, yapf_pex = await MultiGet(source_files_get, yapf_pex_get)

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    config_files = await Get(
        ConfigFiles, ConfigFilesRequest, yapf.config_request(source_files_snapshot.dirs)
    )

    input_digest = await Get(
        Digest, MergeDigests((source_files_snapshot.digest, config_files.snapshot.digest))
    )

    process = await Get(
        Process,
        VenvPexProcess(
            yapf_pex,
            argv=generate_argv(
                source_files,
                yapf,
                check_only=setup_request.check_only,
            ),
            input_digest=input_digest,
            output_files=source_files_snapshot.files,
            description=f"Run yapf on {pluralize(len(setup_request.request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with yapf", level=LogLevel.DEBUG)
async def yapf_fmt(request: YapfRequest, yapf: Yapf) -> FmtResult:
    if yapf.skip:
        return FmtResult.skip(formatter_name="yapf")
    setup = await Get(Setup, SetupRequest(request, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result,
        original_digest=setup.original_digest,
        formatter_name="yapf",
    )


@rule(desc="Lint with yapf", level=LogLevel.DEBUG)
async def yapf_lint(request: YapfRequest, yapf: Yapf) -> LintResults:
    if yapf.skip:
        return LintResults([], linter_name="yapf")
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return LintResults(
        [LintResult.from_fallible_process_result(result)],
        linter_name="yapf",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PythonFmtRequest, YapfRequest),
        UnionRule(LintRequest, YapfRequest),
        *pex.rules(),
    ]
