# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.black.skip_field import SkipBlackField
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.python_fmt import PythonFmtRequest
from pants.backend.python.target_types import InterpreterConstraintsField, PythonSources
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import (
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
    VenvPex,
    VenvPexProcess,
)
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class BlackFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipBlackField).value


class BlackRequest(PythonFmtRequest, LintRequest):
    field_set_type = BlackFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: BlackRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


def generate_argv(source_files: SourceFiles, black: Black, *, check_only: bool) -> Tuple[str, ...]:
    args = []
    if check_only:
        args.append("--check")
    if black.config:
        args.extend(["--config", black.config])
    args.extend(black.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def setup_black(
    setup_request: SetupRequest, black: Black, python_setup: PythonSetup
) -> Setup:
    # Black requires 3.6+ but uses the typed-ast library to work with 2.7, 3.4, 3.5, 3.6, and 3.7.
    # However, typed-ast does not understand 3.8+, so instead we must run Black with Python 3.8+
    # when relevant. We only do this if if <3.8 can't be used, as we don't want a loose requirement
    # like `>=3.6` to result in requiring Python 3.8, which would error if 3.8 is not installed on
    # the machine.
    all_interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (field_set.interpreter_constraints for field_set in setup_request.request.field_sets),
        python_setup,
    )
    tool_interpreter_constraints = (
        all_interpreter_constraints
        if (
            all_interpreter_constraints.requires_python38_or_newer()
            and black.options.is_default("interpreter_constraints")
        )
        else PexInterpreterConstraints(black.interpreter_constraints)
    )

    black_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="black.pex",
            internal_only=True,
            requirements=PexRequirements(black.all_requirements),
            interpreter_constraints=tool_interpreter_constraints,
            main=black.main,
        ),
    )

    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets),
    )

    source_files, black_pex = await MultiGet(source_files_get, black_pex_get)
    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    config_files = await Get(
        ConfigFiles, ConfigFilesRequest, black.config_request(source_files_snapshot.dirs)
    )
    input_digest = await Get(
        Digest, MergeDigests((source_files_snapshot.digest, config_files.snapshot.digest))
    )

    process = await Get(
        Process,
        VenvPexProcess(
            black_pex,
            argv=generate_argv(source_files, black, check_only=setup_request.check_only),
            input_digest=input_digest,
            output_files=source_files_snapshot.files,
            description=f"Run Black on {pluralize(len(setup_request.request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with Black", level=LogLevel.DEBUG)
async def black_fmt(field_sets: BlackRequest, black: Black) -> FmtResult:
    if black.skip:
        return FmtResult.skip(formatter_name="Black")
    setup = await Get(Setup, SetupRequest(field_sets, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result,
        original_digest=setup.original_digest,
        formatter_name="Black",
        strip_chroot_path=True,
    )


@rule(desc="Lint with Black", level=LogLevel.DEBUG)
async def black_lint(field_sets: BlackRequest, black: Black) -> LintResults:
    if black.skip:
        return LintResults([], linter_name="Black")
    setup = await Get(Setup, SetupRequest(field_sets, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return LintResults(
        [LintResult.from_fallible_process_result(result, strip_chroot_path=True)],
        linter_name="Black",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PythonFmtRequest, BlackRequest),
        UnionRule(LintRequest, BlackRequest),
        *pex.rules(),
    ]
