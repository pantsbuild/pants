# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.flake8.subsystem import Flake8
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.targets import PythonInterpreterCompatibility, PythonSources
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import FallibleProcessResult, Process
from pants.engine.rules import UnionRule, named_rule, subsystem_rule
from pants.engine.selectors import Get
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.rules.core import determine_source_files, strip_source_roots
from pants.rules.core.determine_source_files import (
    AllSourceFilesRequest,
    SourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.rules.core.lint import LinterConfiguration, LinterConfigurations, LintResult


@dataclass(frozen=True)
class Flake8Configuration(LinterConfiguration):
    required_fields = (PythonSources,)

    sources: PythonSources
    compatibility: PythonInterpreterCompatibility


class Flake8Configurations(LinterConfigurations):
    config_type = Flake8Configuration


def generate_args(*, specified_source_files: SourceFiles, flake8: Flake8) -> Tuple[str, ...]:
    args = []
    if flake8.options.config is not None:
        args.append(f"--config={flake8.options.config}")
    args.extend(flake8.options.args)
    args.extend(sorted(specified_source_files.snapshot.files))
    return tuple(args)


@named_rule(desc="Lint using Flake8")
async def flake8_lint(
    configs: Flake8Configurations,
    flake8: Flake8,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
    if flake8.options.skip:
        return LintResult.noop()

    # NB: Flake8 output depends upon which Python interpreter version it's run with. We ensure that
    # each target runs with its own interpreter constraints. See
    # http://flake8.pycqa.org/en/latest/user/invocation.html.
    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (config.compatibility for config in configs), python_setup
    )
    requirements_pex = await Get[Pex](
        PexRequest(
            output_filename="flake8.pex",
            requirements=PexRequirements(flake8.get_requirement_specs()),
            interpreter_constraints=interpreter_constraints,
            entry_point=flake8.get_entry_point(),
        )
    )

    config_path: Optional[str] = flake8.options.config
    config_snapshot = await Get[Snapshot](
        PathGlobs(
            globs=tuple([config_path] if config_path else []),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--flake8-config`",
        )
    )

    all_source_files = await Get[SourceFiles](
        AllSourceFilesRequest(config.sources for config in configs)
    )
    specified_source_files = await Get[SourceFiles](
        SpecifiedSourceFilesRequest((config.sources, config.origin) for config in configs)
    )

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                all_source_files.snapshot.directory_digest,
                requirements_pex.directory_digest,
                config_snapshot.directory_digest,
            )
        ),
    )

    address_references = ", ".join(sorted(config.address.reference() for config in configs))

    request = requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./flake8.pex",
        pex_args=generate_args(specified_source_files=specified_source_files, flake8=flake8),
        input_files=merged_input_files,
        description=f"Run Flake8 for {address_references}",
    )
    result = await Get[FallibleProcessResult](Process, request)
    return LintResult.from_fallible_process_result(result)


def rules():
    return [
        flake8_lint,
        subsystem_rule(Flake8),
        UnionRule(LinterConfigurations, Flake8Configurations),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
