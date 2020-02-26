# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import List, Optional, Tuple

from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.python_format_target import PythonFormatTarget
from pants.backend.python.lint.python_lint_target import PythonLintTarget
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import (
    CreatePex,
    Pex,
    PexInterpreterConstraints,
    PexRequirements,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import (
    ExecuteProcessRequest,
    ExecuteProcessResult,
    FallibleExecuteProcessResult,
)
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.option.custom_types import GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.rules.core import determine_source_files, strip_source_roots
from pants.rules.core.determine_source_files import (
    AllSourceFilesRequest,
    SourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult


@dataclass(frozen=True)
class IsortTarget:
    adaptor_with_origin: TargetAdaptorWithOrigin
    prior_formatter_result: Optional[Snapshot] = None  # unused by `lint`


@dataclass(frozen=True)
class SetupRequest:
    target: IsortTarget
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process_request: ExecuteProcessRequest


def generate_args(
    *, specified_source_files: SourceFiles, isort: Isort, check_only: bool,
) -> Tuple[str, ...]:
    # NB: isort auto-discovers config files. There is no way to hardcode them via command line
    # flags. So long as the files are in the Pex's input files, isort will use the config.
    args = []
    if check_only:
        args.append("--check-only")
    args.extend(isort.options.args)
    args.extend(sorted(specified_source_files.snapshot.files))
    return tuple(args)


@rule
async def setup(
    request: SetupRequest,
    isort: Isort,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> Setup:
    adaptor_with_origin = request.target.adaptor_with_origin
    adaptor = adaptor_with_origin.adaptor

    requirements_pex = await Get[Pex](
        CreatePex(
            output_filename="isort.pex",
            requirements=PexRequirements(requirements=tuple(isort.get_requirement_specs())),
            interpreter_constraints=PexInterpreterConstraints(
                constraint_set=tuple(isort.default_interpreter_constraints)
            ),
            entry_point=isort.get_entry_point(),
        )
    )

    config_path: Optional[List[str]] = isort.options.config
    config_snapshot = await Get[Snapshot](
        PathGlobs(
            globs=config_path or (),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            conjunction=GlobExpansionConjunction.all_match,
            description_of_origin="the option `--isort-config`",
        )
    )

    if request.target.prior_formatter_result is None:
        all_source_files = await Get[SourceFiles](AllSourceFilesRequest([adaptor]))
        all_source_files_snapshot = all_source_files.snapshot
    else:
        all_source_files_snapshot = request.target.prior_formatter_result

    specified_source_files = await Get[SourceFiles](
        SpecifiedSourceFilesRequest([adaptor_with_origin])
    )

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                all_source_files_snapshot.directory_digest,
                requirements_pex.directory_digest,
                config_snapshot.directory_digest,
            )
        ),
    )

    process_request = requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./isort.pex",
        pex_args=generate_args(
            specified_source_files=specified_source_files,
            isort=isort,
            check_only=request.check_only,
        ),
        input_files=merged_input_files,
        output_files=all_source_files_snapshot.files,
        description=f"Run isort for {adaptor.address.reference()}",
    )
    return Setup(process_request)


@rule(name="Format using isort")
async def fmt(isort_target: IsortTarget, isort: Isort) -> FmtResult:
    if isort.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(isort_target, check_only=False))
    result = await Get[ExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
    return FmtResult.from_execute_process_result(result)


@rule(name="Lint using isort")
async def lint(isort_target: IsortTarget, isort: Isort) -> LintResult:
    if isort.options.skip:
        return LintResult.noop()
    setup = await Get[Setup](SetupRequest(isort_target, check_only=True))
    result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
    return LintResult.from_fallible_execute_process_result(result)


def rules():
    return [
        setup,
        fmt,
        lint,
        subsystem_rule(Isort),
        UnionRule(PythonFormatTarget, IsortTarget),
        UnionRule(PythonLintTarget, IsortTarget),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
