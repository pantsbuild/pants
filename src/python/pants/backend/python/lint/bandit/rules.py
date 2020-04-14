# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.bandit.subsystem import Bandit
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
class BanditConfiguration(LinterConfiguration):
    required_fields = (PythonSources,)

    sources: PythonSources
    compatibility: PythonInterpreterCompatibility


class BanditConfigurations(LinterConfigurations):
    config_type = BanditConfiguration


def generate_args(*, specified_source_files: SourceFiles, bandit: Bandit) -> Tuple[str, ...]:
    args = []
    if bandit.options.config is not None:
        args.append(f"--config={bandit.options.config}")
    args.extend(bandit.options.args)
    args.extend(sorted(specified_source_files.snapshot.files))
    return tuple(args)


@named_rule(desc="Lint using Bandit")
async def bandit_lint(
    configs: BanditConfigurations,
    bandit: Bandit,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
    if bandit.options.skip:
        return LintResult.noop()

    # NB: Bandit output depends upon which Python interpreter version it's run with. See
    # https://github.com/PyCQA/bandit#under-which-version-of-python-should-i-install-bandit.
    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (config.compatibility for config in configs), python_setup=python_setup
    )
    requirements_pex = await Get[Pex](
        PexRequest(
            output_filename="bandit.pex",
            requirements=PexRequirements(bandit.get_requirement_specs()),
            interpreter_constraints=interpreter_constraints,
            entry_point=bandit.get_entry_point(),
        )
    )

    config_path: Optional[str] = bandit.options.config
    config_snapshot = await Get[Snapshot](
        PathGlobs(
            globs=tuple([config_path] if config_path else []),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--bandit-config`",
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
        pex_path=f"./bandit.pex",
        pex_args=generate_args(specified_source_files=specified_source_files, bandit=bandit),
        input_files=merged_input_files,
        description=f"Run Bandit for {address_references}",
    )
    result = await Get[FallibleProcessResult](Process, request)
    return LintResult.from_fallible_process_result(result)


def rules():
    return [
        bandit_lint,
        subsystem_rule(Bandit),
        UnionRule(LinterConfigurations, BanditConfigurations),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
