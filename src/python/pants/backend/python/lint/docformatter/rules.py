# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.docformatter.subsystem import Docformatter
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
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.isolated_process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import UnionRule, named_rule, rule, subsystem_rule
from pants.engine.selectors import Get
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
class DocformatterConfiguration(FmtConfiguration):
    required_fields = (PythonSources,)

    sources: PythonSources


class DocformatterConfigurations(FmtConfigurations):
    config_type = DocformatterConfiguration


@dataclass(frozen=True)
class SetupRequest:
    configs: DocformatterConfigurations
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process


def generate_args(
    *, specified_source_files: SourceFiles, docformatter: Docformatter, check_only: bool,
) -> Tuple[str, ...]:
    return (
        "--check" if check_only else "--in-place",
        *docformatter.options.args,
        *sorted(specified_source_files.snapshot.files),
    )


@rule
async def setup(
    request: SetupRequest,
    docformatter: Docformatter,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> Setup:
    requirements_pex = await Get[Pex](
        PexRequest(
            output_filename="docformatter.pex",
            requirements=PexRequirements(docformatter.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                docformatter.default_interpreter_constraints
            ),
            entry_point=docformatter.get_entry_point(),
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
            )
        ),
    )

    address_references = ", ".join(sorted(config.address.reference() for config in request.configs))

    process = requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./docformatter.pex",
        pex_args=generate_args(
            specified_source_files=specified_source_files,
            docformatter=docformatter,
            check_only=request.check_only,
        ),
        input_files=merged_input_files,
        output_files=all_source_files_snapshot.files,
        description=f"Run docformatter for {address_references}",
    )
    return Setup(process)


@named_rule(desc="Format Python docstrings with docformatter")
async def docformatter_fmt(
    configs: DocformatterConfigurations, docformatter: Docformatter
) -> FmtResult:
    if docformatter.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(configs, check_only=False))
    result = await Get[ProcessResult](Process, setup.process)
    return FmtResult.from_process_result(result)


@named_rule(desc="Lint Python docstrings with docformatter")
async def docformatter_lint(
    configs: DocformatterConfigurations, docformatter: Docformatter
) -> LintResult:
    if docformatter.options.skip:
        return LintResult.noop()
    setup = await Get[Setup](SetupRequest(configs, check_only=True))
    result = await Get[FallibleProcessResult](Process, setup.process)
    return LintResult.from_fallible_process_result(result)


def rules():
    return [
        setup,
        docformatter_fmt,
        docformatter_lint,
        subsystem_rule(Docformatter),
        UnionRule(PythonFmtConfigurations, DocformatterConfigurations),
        UnionRule(LinterConfigurations, DocformatterConfigurations),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
