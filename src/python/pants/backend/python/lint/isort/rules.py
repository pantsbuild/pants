# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import List, Optional, Tuple

from pants.backend.python.lint.isort.subsystem import Isort
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
from pants.engine.fs import EMPTY_SNAPSHOT, Digest, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import FieldSetWithOrigin
from pants.engine.unions import UnionRule
from pants.option.custom_types import GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class IsortFieldSet(FieldSetWithOrigin):
    required_fields = (PythonSources,)

    sources: PythonSources


class IsortRequest(PythonFmtRequest, LintRequest):
    field_set_type = IsortFieldSet


@dataclass(frozen=True)
class SetupRequest:
    request: IsortRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


def generate_args(
    *, specified_source_files: SourceFiles, isort: Isort, check_only: bool,
) -> Tuple[str, ...]:
    # NB: isort auto-discovers config files. There is no way to hardcode them via command line
    # flags. So long as the files are in the Pex's input files, isort will use the config.
    args = []
    if check_only:
        args.append("--check-only")
    args.extend(isort.options.args)
    args.extend(specified_source_files.files)
    return tuple(args)


@rule
async def setup(
    setup_request: SetupRequest,
    isort: Isort,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> Setup:
    requirements_pex_request = Get[Pex](
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
    config_snapshot_request = Get[Snapshot](
        PathGlobs(
            globs=config_path or (),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            conjunction=GlobExpansionConjunction.all_match,
            description_of_origin="the option `--isort-config`",
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

    requests = (
        requirements_pex_request,
        config_snapshot_request,
        specified_source_files_request,
    )
    all_source_files, requirements_pex, config_snapshot, specified_source_files = (
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
        MergeDigests(
            (all_source_files_snapshot.digest, requirements_pex.digest, config_snapshot.digest)
        )
    )

    address_references = ", ".join(
        sorted(field_set.address.reference() for field_set in setup_request.request.field_sets)
    )

    process = requirements_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./isort.pex",
        pex_args=generate_args(
            specified_source_files=specified_source_files,
            isort=isort,
            check_only=setup_request.check_only,
        ),
        input_digest=input_digest,
        output_files=all_source_files_snapshot.files,
        description=(
            f"Run isort on {pluralize(len(setup_request.request.field_sets), 'target')}: {address_references}."
        ),
    )
    return Setup(process, original_digest=all_source_files_snapshot.digest)


@rule(desc="Format using isort")
async def isort_fmt(request: IsortRequest, isort: Isort) -> FmtResult:
    if isort.options.skip:
        return FmtResult.noop()
    setup = await Get[Setup](SetupRequest(request, check_only=False))
    result = await Get[ProcessResult](Process, setup.process)
    return FmtResult.from_process_result(
        result,
        original_digest=setup.original_digest,
        formatter_name="isort",
        strip_chroot_path=True,
    )


@rule(desc="Lint using isort")
async def isort_lint(request: IsortRequest, isort: Isort) -> LintResults:
    if isort.options.skip:
        return LintResults()
    setup = await Get[Setup](SetupRequest(request, check_only=True))
    result = await Get[FallibleProcessResult](Process, setup.process)
    return LintResults(
        [
            LintResult.from_fallible_process_result(
                result, linter_name="isort", strip_chroot_path=True
            )
        ]
    )


def rules():
    return [
        setup,
        isort_fmt,
        isort_lint,
        SubsystemRule(Isort),
        UnionRule(PythonFmtRequest, IsortRequest),
        UnionRule(LintRequest, IsortRequest),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
