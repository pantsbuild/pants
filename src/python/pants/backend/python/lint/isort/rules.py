# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.isort.skip_field import SkipIsortField
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.python_fmt import PythonFmtRequest
from pants.backend.python.target_types import PythonSources
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import (
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
    PexResolveInfo,
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
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class IsortFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipIsortField).value


class IsortRequest(PythonFmtRequest, LintRequest):
    field_set_type = IsortFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: IsortRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


def generate_argv(
    source_files: SourceFiles, isort: Isort, *, is_isort5: bool, check_only: bool
) -> Tuple[str, ...]:
    args = [*isort.args]
    if check_only:
        args.append("--check-only")
    if is_isort5 and len(isort.config) == 1:
        explicitly_configured_config_args = [
            arg
            for arg in isort.args
            if (
                arg.startswith("--sp")
                or arg.startswith("--settings-path")
                or arg.startswith("--settings-file")
                or arg.startswith("--settings")
            )
        ]
        # TODO: Deprecate manually setting this option, but wait until we deprecate
        #  `[isort].config` to be a string rather than list[str] option.
        if not explicitly_configured_config_args:
            args.append(f"--settings={isort.config[0]}")
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def setup_isort(setup_request: SetupRequest, isort: Isort) -> Setup:
    isort_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="isort.pex",
            internal_only=True,
            requirements=PexRequirements(isort.all_requirements),
            interpreter_constraints=PexInterpreterConstraints(isort.interpreter_constraints),
            main=isort.main,
        ),
    )
    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets),
    )
    source_files, isort_pex = await MultiGet(source_files_get, isort_pex_get)

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    config_files = await Get(
        ConfigFiles, ConfigFilesRequest, isort.config_request(source_files_snapshot.dirs)
    )

    # Isort 5+ changes how config files are handled. Determine which semantics we should use.
    is_isort5 = False
    if isort.config:
        isort_info = await Get(PexResolveInfo, VenvPex, isort_pex)
        is_isort5 = any(
            dist_info.project_name == "isort" and dist_info.version.major >= 5
            for dist_info in isort_info
        )

    input_digest = await Get(
        Digest, MergeDigests((source_files_snapshot.digest, config_files.snapshot.digest))
    )

    process = await Get(
        Process,
        VenvPexProcess(
            isort_pex,
            argv=generate_argv(
                source_files, isort, is_isort5=is_isort5, check_only=setup_request.check_only
            ),
            input_digest=input_digest,
            output_files=source_files_snapshot.files,
            description=f"Run isort on {pluralize(len(setup_request.request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with isort", level=LogLevel.DEBUG)
async def isort_fmt(request: IsortRequest, isort: Isort) -> FmtResult:
    if isort.skip:
        return FmtResult.skip(formatter_name="isort")
    setup = await Get(Setup, SetupRequest(request, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result,
        original_digest=setup.original_digest,
        formatter_name="isort",
        strip_chroot_path=True,
    )


@rule(desc="Lint with isort", level=LogLevel.DEBUG)
async def isort_lint(request: IsortRequest, isort: Isort) -> LintResults:
    if isort.skip:
        return LintResults([], linter_name="isort")
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return LintResults(
        [LintResult.from_fallible_process_result(result, strip_chroot_path=True)],
        linter_name="isort",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PythonFmtRequest, IsortRequest),
        UnionRule(LintRequest, IsortRequest),
        *pex.rules(),
    ]
