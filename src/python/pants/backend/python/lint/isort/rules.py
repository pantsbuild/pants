# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import List, Optional, Tuple

from pants.backend.python.lint.isort.subsystem import Isort
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
from pants.option.custom_types import GlobExpansionConjunction
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
class IsortConfiguration(FmtConfiguration):
    required_fields = (PythonSources,)

    sources: PythonSources


class IsortConfigurations(FmtConfigurations):
    config_type = IsortConfiguration


@dataclass(frozen=True)
class SetupRequest:
    configs: IsortConfigurations
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process


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
    requirements_pex = await Get[Pex](
        PexRequest(
            output_filename="isort.pex",
            requirements=PexRequirements(isort.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                isort.default_interpreter_constraints
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
        pex_path="./isort.pex",
        pex_args=generate_args(
            specified_source_files=specified_source_files,
            isort=isort,
            check_only=request.check_only,
        ),
        input_files=merged_input_files,
        output_files=all_source_files_snapshot.files,
        description=f"Run isort for {address_references}",
    )
    return Setup(process)


@named_rule(desc="Format using isort")
async def isort_fmt(configs: IsortConfigurations, isort: Isort) -> FmtResult:
    if isort.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(configs, check_only=False))
    result = await Get[ProcessResult](Process, setup.process)
    return FmtResult.from_process_result(result)


@named_rule(desc="Lint using isort")
async def isort_lint(configs: IsortConfigurations, isort: Isort) -> LintResult:
    if isort.options.skip:
        return LintResult.noop()
    setup = await Get[Setup](SetupRequest(configs, check_only=True))
    result = await Get[FallibleProcessResult](Process, setup.process)
    return LintResult.from_fallible_process_result(result)


def rules():
    return [
        setup,
        isort_fmt,
        isort_lint,
        subsystem_rule(Isort),
        UnionRule(PythonFmtConfigurations, IsortConfigurations),
        UnionRule(LinterConfigurations, IsortConfigurations),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
