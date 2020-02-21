# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional, Tuple

from pants.backend.python.lint.black.subsystem import Black
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
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.rules.core import find_target_source_files, strip_source_roots
from pants.rules.core.find_target_source_files import (
    FindTargetSourceFilesRequest,
    TargetSourceFiles,
)
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult


@dataclass(frozen=True)
class BlackTarget:
    adaptor_with_origin: TargetAdaptorWithOrigin
    prior_formatter_result_digest: Optional[Digest] = None  # unused by `lint`


@dataclass(frozen=True)
class SetupRequest:
    target: BlackTarget
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process_request: ExecuteProcessRequest


def generate_args(
    *, source_files: TargetSourceFiles, black: Black, check_only: bool,
) -> Tuple[str, ...]:
    args = []
    if check_only:
        args.append("--check")
    if black.options.config is not None:
        args.extend(["--config", black.options.config])
    args.extend(black.options.args)
    # NB: For some reason, Black's --exclude option only works on recursive invocations, meaning
    # calling Black on a directory(s) and letting it auto-discover files. However, we don't want
    # Black to run over everything recursively under the directory of our target, as Black should
    # only touch files directly specified. We can use `--include` to ensure that Black only
    # operates on the files we actually care about.
    files = sorted(source_files.snapshot.files)
    args.extend(["--include", "|".join(re.escape(f) for f in files)])
    args.extend(PurePath(f).parent.as_posix() for f in files)
    return tuple(args)


@rule
async def setup(
    request: SetupRequest,
    black: Black,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> Setup:
    adaptor_with_origin = request.target.adaptor_with_origin
    adaptor = adaptor_with_origin.adaptor

    requirements_pex = await Get[Pex](
        CreatePex(
            output_filename="black.pex",
            requirements=PexRequirements(requirements=tuple(black.get_requirement_specs())),
            interpreter_constraints=PexInterpreterConstraints(
                constraint_set=tuple(black.default_interpreter_constraints)
            ),
            entry_point=black.get_entry_point(),
        )
    )

    config_path: Optional[str] = black.options.config
    config_snapshot = await Get[Snapshot](
        PathGlobs(
            globs=tuple([config_path] if config_path else []),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--black-config`",
        )
    )

    # NB: We populate the chroot with every source file belonging to the target, but possibly only
    # tell Black to run over some of those files when given file arguments.
    full_sources_digest = (
        request.target.prior_formatter_result_digest or adaptor.sources.snapshot.directory_digest
    )
    specified_source_files = await Get[TargetSourceFiles](
        FindTargetSourceFilesRequest(adaptor_with_origin)
    )

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                full_sources_digest,
                requirements_pex.directory_digest,
                config_snapshot.directory_digest,
            )
        ),
    )

    process_request = requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./black.pex",
        pex_args=generate_args(
            source_files=specified_source_files, black=black, check_only=request.check_only,
        ),
        input_files=merged_input_files,
        # NB: Even if the user specified to only run on certain files belonging to the target, we
        # still capture in the output all of the source files.
        output_files=adaptor.sources.snapshot.files,
        description=f"Run black for {adaptor.address.reference()}",
    )
    return Setup(process_request)


@rule(name="Format using Black")
async def fmt(black_target: BlackTarget, black: Black) -> FmtResult:
    if black.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(black_target, check_only=False))
    result = await Get[ExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
    return FmtResult.from_execute_process_result(result)


@rule(name="Lint using Black")
async def lint(black_target: BlackTarget, black: Black) -> LintResult:
    if black.options.skip:
        return LintResult.noop()
    setup = await Get[Setup](SetupRequest(black_target, check_only=True))
    result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
    return LintResult.from_fallible_execute_process_result(result)


def rules():
    return [
        setup,
        fmt,
        lint,
        subsystem_rule(Black),
        UnionRule(PythonFormatTarget, BlackTarget),
        UnionRule(PythonLintTarget, BlackTarget),
        *download_pex_bin.rules(),
        *find_target_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
