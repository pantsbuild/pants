# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.lint.python_formatter import PythonFormatTarget, PythonFormatter
from pants.backend.python.lint.python_linter import PythonLintTarget
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import (
    CreatePex,
    Pex,
    PexInterpreterConstraints,
    PexRequirements,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.isolated_process import (
    ExecuteProcessRequest,
    ExecuteProcessResult,
    FallibleExecuteProcessResult,
)
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
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
class DocformatterFormatter(PythonFormatter):
    pass


@dataclass(frozen=True)
class SetupRequest:
    formatter: DocformatterFormatter
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process_request: ExecuteProcessRequest


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
    adaptors_with_origins = request.formatter.adaptors_with_origins

    requirements_pex = await Get[Pex](
        CreatePex(
            output_filename="docformatter.pex",
            requirements=PexRequirements(requirements=tuple(docformatter.get_requirement_specs())),
            interpreter_constraints=PexInterpreterConstraints(
                constraint_set=tuple(docformatter.default_interpreter_constraints)
            ),
            entry_point=docformatter.get_entry_point(),
        )
    )

    if request.formatter.prior_formatter_result is None:
        all_source_files = await Get[SourceFiles](
            AllSourceFilesRequest(
                adaptor_with_origin.adaptor for adaptor_with_origin in adaptors_with_origins
            )
        )
        all_source_files_snapshot = all_source_files.snapshot
    else:
        all_source_files_snapshot = request.formatter.prior_formatter_result

    specified_source_files = await Get[SourceFiles](
        SpecifiedSourceFilesRequest(adaptors_with_origins)
    )

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                all_source_files_snapshot.directory_digest,
                requirements_pex.directory_digest,
            )
        ),
    )

    address_references = ", ".join(
        sorted(
            adaptor_with_origin.adaptor.address.reference()
            for adaptor_with_origin in adaptors_with_origins
        )
    )

    process_request = requirements_pex.create_execute_request(
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
    return Setup(process_request)


@rule(name="Format Python docstrings with docformatter")
async def fmt(formatter: DocformatterFormatter, docformatter: Docformatter) -> FmtResult:
    if docformatter.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(formatter, check_only=False))
    result = await Get[ExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
    return FmtResult.from_execute_process_result(result)


@rule(name="Lint Python docstrings with docformatter")
async def lint(formatter: DocformatterFormatter, docformatter: Docformatter) -> LintResult:
    if docformatter.options.skip:
        return LintResult.noop()
    setup = await Get[Setup](SetupRequest(formatter, check_only=True))
    result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
    return LintResult.from_fallible_execute_process_result(result)


def rules():
    return [
        setup,
        fmt,
        lint,
        subsystem_rule(Docformatter),
        UnionRule(PythonFormatTarget, DocformatterFormatter),
        UnionRule(PythonLintTarget, DocformatterFormatter),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
