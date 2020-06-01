# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.lint.python_fmt import PythonFmtRequest
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import PythonSources
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.core.util_rules.determine_source_files import (
    AllSourceFilesRequest,
    SourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.engine.fs import EMPTY_SNAPSHOT, Digest, MergeDigests
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import FieldSetWithOrigin
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class DocformatterFieldSet(FieldSetWithOrigin):
    required_fields = (PythonSources,)

    sources: PythonSources


class DocformatterRequest(PythonFmtRequest, LintRequest):
    field_set_type = DocformatterFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: DocformatterRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


def generate_args(
    *, specified_source_files: SourceFiles, docformatter: Docformatter, check_only: bool,
) -> Tuple[str, ...]:
    return (
        "--check" if check_only else "--in-place",
        *docformatter.options.args,
        *specified_source_files.files,
    )


@rule
async def setup(
    setup_request: SetupRequest,
    docformatter: Docformatter,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> Setup:
    requirements_pex_request = Get[Pex](
        PexRequest(
            output_filename="docformatter.pex",
            requirements=PexRequirements(docformatter.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                docformatter.default_interpreter_constraints
            ),
            entry_point=docformatter.get_entry_point(),
        )
    )

    all_source_files_request = Get[SourceFiles](
        AllSourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets)
    )
    specified_source_files_request = Get[SourceFiles](
        SpecifiedSourceFilesRequest(
            (field_set.sources, field_set.origin) for field_set in setup_request.request.field_sets
        )
    )

    requests = requirements_pex_request, specified_source_files_request
    all_source_files, requirements_pex, specified_source_files = (
        await MultiGet(all_source_files_request, *requests)
        if setup_request.request.prior_formatter_result is None
        else (SourceFiles(EMPTY_SNAPSHOT), *await MultiGet(*requests))
    )
    all_source_files_snapshot = (
        all_source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    input_digest = await Get[Digest](
        MergeDigests((all_source_files_snapshot.digest, requirements_pex.digest))
    )

    address_references = ", ".join(
        sorted(field_set.address.reference() for field_set in setup_request.request.field_sets)
    )

    process = requirements_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./docformatter.pex",
        pex_args=generate_args(
            specified_source_files=specified_source_files,
            docformatter=docformatter,
            check_only=setup_request.check_only,
        ),
        input_digest=input_digest,
        output_files=all_source_files_snapshot.files,
        description=(
            f"Run Docformatter on {pluralize(len(setup_request.request.field_sets), 'target')}: "
            f"{address_references}."
        ),
    )
    return Setup(process, original_digest=all_source_files_snapshot.digest)


@rule(desc="Format Python docstrings with docformatter")
async def docformatter_fmt(request: DocformatterRequest, docformatter: Docformatter) -> FmtResult:
    if docformatter.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(request, check_only=False))
    result = await Get[ProcessResult](Process, setup.process)
    return FmtResult.from_process_result(
        result, original_digest=setup.original_digest, formatter_name="Docformatter"
    )


@rule(desc="Lint Python docstrings with docformatter")
async def docformatter_lint(
    request: DocformatterRequest, docformatter: Docformatter
) -> LintResults:
    if docformatter.options.skip:
        return LintResults()
    setup = await Get[Setup](SetupRequest(request, check_only=True))
    result = await Get[FallibleProcessResult](Process, setup.process)
    return LintResults(
        [LintResult.from_fallible_process_result(result, linter_name="Docformatter")]
    )


def rules():
    return [
        setup,
        docformatter_fmt,
        docformatter_lint,
        SubsystemRule(Docformatter),
        UnionRule(PythonFmtRequest, DocformatterRequest),
        UnionRule(LintRequest, DocformatterRequest),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
