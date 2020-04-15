# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.rules import download_pex_bin, importable_python_sources, pex
from pants.backend.python.rules.importable_python_sources import ImportablePythonSources
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.targets import PythonInterpreterCompatibility, PythonSources
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.addressable import Addresses
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import FallibleProcessResult, Process
from pants.engine.rules import UnionRule, named_rule, subsystem_rule
from pants.engine.selectors import Get
from pants.engine.target import Dependencies, Targets
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.rules.core import determine_source_files, strip_source_roots
from pants.rules.core.determine_source_files import SourceFiles, SpecifiedSourceFilesRequest
from pants.rules.core.lint import LinterConfiguration, LinterConfigurations, LintResult


@dataclass(frozen=True)
class PylintConfiguration(LinterConfiguration):
    required_fields = (PythonSources,)

    sources: PythonSources
    dependencies: Dependencies
    compatibility: PythonInterpreterCompatibility


class PylintConfigurations(LinterConfigurations):
    config_type = PylintConfiguration


def generate_args(*, specified_source_files: SourceFiles, pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.options.config is not None:
        args.append(f"--rcfile={pylint.options.config}")
    args.extend(pylint.options.args)
    args.extend(sorted(specified_source_files.snapshot.files))
    return tuple(args)


@named_rule(desc="Lint using Pylint")
async def pylint_lint(
    configs: PylintConfigurations,
    pylint: Pylint,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
    if pylint.options.skip:
        return LintResult.noop()

    # Pylint needs direct dependencies in the chroot to ensure that imports are valid. However, it
    # doesn't lint those direct dependencies nor does it care about transitive dependencies.
    addresses = []
    for config in configs:
        addresses.append(config.address)
        addresses.extend(config.dependencies.value or ())
    targets = await Get[Targets](Addresses(addresses))
    chrooted_python_sources = await Get[ImportablePythonSources](Targets, targets)

    # NB: Pylint output depends upon which Python interpreter version it's run with. We ensure that
    # each target runs with its own interpreter constraints. See
    # http://pylint.pycqa.org/en/latest/faq.html#what-versions-of-python-is-pylint-supporting.
    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (config.compatibility for config in configs), python_setup
    )
    requirements_pex = await Get[Pex](
        PexRequest(
            output_filename="pylint.pex",
            requirements=PexRequirements(pylint.get_requirement_specs()),
            interpreter_constraints=interpreter_constraints,
            entry_point=pylint.get_entry_point(),
        )
    )

    config_path: Optional[str] = pylint.options.config
    config_snapshot = await Get[Snapshot](
        PathGlobs(
            globs=tuple([config_path] if config_path else []),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--pylint-config`",
        )
    )

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                requirements_pex.directory_digest,
                config_snapshot.directory_digest,
                chrooted_python_sources.snapshot.directory_digest,
            )
        ),
    )

    specified_source_files = await Get[SourceFiles](
        SpecifiedSourceFilesRequest(
            ((config.sources, config.origin) for config in configs), strip_source_roots=True
        )
    )

    address_references = ", ".join(sorted(config.address.reference() for config in configs))

    request = requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./pylint.pex",
        pex_args=generate_args(specified_source_files=specified_source_files, pylint=pylint),
        input_files=merged_input_files,
        description=f"Run Pylint for {address_references}",
    )
    result = await Get[FallibleProcessResult](Process, request)
    return LintResult.from_fallible_process_result(result)


def rules():
    return [
        pylint_lint,
        subsystem_rule(Pylint),
        UnionRule(LinterConfigurations, PylintConfigurations),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *importable_python_sources.rules(),
        *strip_source_roots.rules(),
        *python_native_code.rules(),
        *subprocess_environment.rules(),
    ]
