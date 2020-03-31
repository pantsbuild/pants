# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional, Tuple

from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.python_formatter import PythonFormatter
from pants.backend.python.rules import download_pex_bin, hermetic_pex, pex
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
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.rules.core import determine_source_files, strip_source_roots
from pants.rules.core.determine_source_files import (
    LegacyAllSourceFilesRequest,
    LegacySpecifiedSourceFilesRequest,
    SourceFiles,
)
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import Linter, LintResult


@dataclass(frozen=True)
class BlackFormatter(PythonFormatter):
    pass


@dataclass(frozen=True)
class SetupRequest:
    formatter: BlackFormatter
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process_request: ExecuteProcessRequest


def generate_args(
    *, specified_source_files: SourceFiles, black: Black, check_only: bool,
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
    files = sorted(specified_source_files.snapshot.files)
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
    adaptors_with_origins = request.formatter.adaptors_with_origins

    requirements_pex = await Get[Pex](
        CreatePex(
            output_filename="black.pex",
            requirements=PexRequirements(black.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                black.default_interpreter_constraints
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

    if request.formatter.prior_formatter_result is None:
        all_source_files = await Get[SourceFiles](
            LegacyAllSourceFilesRequest(
                adaptor_with_origin.adaptor for adaptor_with_origin in adaptors_with_origins
            )
        )
        all_source_files_snapshot = all_source_files.snapshot
    else:
        all_source_files_snapshot = request.formatter.prior_formatter_result

    specified_source_files = await Get[SourceFiles](
        LegacySpecifiedSourceFilesRequest(adaptors_with_origins)
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

    address_references = ", ".join(
        sorted(
            adaptor_with_origin.adaptor.address.reference()
            for adaptor_with_origin in adaptors_with_origins
        )
    )

    hermetic_pex_request = requirements_pex.create_hermetic_pex_request(ExecuteProcessRequest(
        argv=generate_args(
            specified_source_files=specified_source_files,
            black=black,
            check_only=request.check_only,
        ),
        input_files=merged_input_files,
        output_files=all_source_files_snapshot.files,
        description=f"Run black for {address_references}",
    ))
    process_request = await Get[ExecuteProcessRequest](HermeticPexRequest, hermetic_pex_request)
    return Setup(process_request)


@rule(name="Format using Black")
async def fmt(formatter: BlackFormatter, black: Black) -> FmtResult:
    if black.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(formatter, check_only=False))
    result = await Get[ExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
    return FmtResult.from_execute_process_result(result)


@rule(name="Lint using Black")
async def lint(formatter: BlackFormatter, black: Black) -> LintResult:
    if black.options.skip:
        return LintResult.noop()
    setup = await Get[Setup](SetupRequest(formatter, check_only=True))
    result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
    return LintResult.from_fallible_execute_process_result(result)


def rules():
    return [
        setup,
        fmt,
        lint,
        subsystem_rule(Black),
        UnionRule(PythonFormatter, BlackFormatter),
        UnionRule(Linter, BlackFormatter),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
