# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional, Tuple

from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.python_fmt import PythonFmtConfigurations
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.targets import PythonSources
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import UnionRule, named_rule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.rules.core import determine_source_files, strip_source_roots
from pants.rules.core.determine_source_files import (
    AllSourceFilesRequest,
    SourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.rules.core.fmt import FmtConfiguration, FmtConfigurations, FmtResult
from pants.rules.core.lint import LinterConfigurations, LintResult


@dataclass(frozen=True)
class BlackConfiguration(FmtConfiguration):
    required_fields = (PythonSources,)

    sources: PythonSources


class BlackConfigurations(FmtConfigurations):
    config_type = BlackConfiguration


@dataclass(frozen=True)
class SetupRequest:
    configs: BlackConfigurations
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process


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
    requirements_pex = await Get[Pex](
        PexRequest(
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

    if request.configs.prior_formatter_result is None:
        all_source_files = await Get[SourceFiles](
            AllSourceFilesRequest(config.sources for config in request.configs)
        )
        all_source_files_snapshot = all_source_files.snapshot
    else:
        all_source_files_snapshot = request.configs.prior_formatter_result

    specified_source_files = await Get[SourceFiles](
        SpecifiedSourceFilesRequest((config.sources, config.origin) for config in request.configs)
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

    address_references = ", ".join(sorted(config.address.reference() for config in request.configs))

    process = requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./black.pex",
        pex_args=generate_args(
            specified_source_files=specified_source_files,
            black=black,
            check_only=request.check_only,
        ),
        input_files=merged_input_files,
        output_files=all_source_files_snapshot.files,
        description=f"Run black for {address_references}",
    )
    return Setup(process)


@named_rule(desc="Format using Black")
async def black_fmt(configs: BlackConfigurations, black: Black) -> FmtResult:
    if black.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(configs, check_only=False))
    result = await Get[ProcessResult](Process, setup.process)
    return FmtResult.from_process_result(result)


@named_rule(desc="Lint using Black")
async def black_lint(configs: BlackConfigurations, black: Black) -> LintResult:
    if black.options.skip:
        return LintResult.noop()
    setup = await Get[Setup](SetupRequest(configs, check_only=True))
    result = await Get[FallibleProcessResult](Process, setup.process)
    return LintResult.from_fallible_process_result(result)


def rules():
    return [
        setup,
        black_fmt,
        black_lint,
        subsystem_rule(Black),
        UnionRule(PythonFmtConfigurations, BlackConfigurations),
        UnionRule(LinterConfigurations, BlackConfigurations),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
