# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Optional, Tuple, cast

from packaging.requirements import Requirement as PackagingRequirement
from pkg_resources import Requirement

from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.python_fmt import PythonFmtRequest
from pants.backend.python.target_types import PythonSources
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import (
    Digest,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IsortFieldSet(FieldSet):
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


def is_old_isort_version(version: Optional[str]) -> bool:
    if version is None:
        return False

    requirement = cast(PackagingRequirement, Requirement.parse(version))
    specifier = requirement.specifier

    old_releases = (
        *[f"4.3.{i}" for i in range(22)],
        *[f"4.2.{i}" for i in range(16)],
        *[f"4.1.{i}" for i in range(3)],
        "4.0.0",
    )
    old_releases_match = any(old_release in specifier for old_release in old_releases)
    if not old_releases_match:
        return False  # if no old release matches, the version must be new

    # if old releases match, the version may still be >=5 (e.g. isort!=5.0.0 or simply isort)
    new_releases_match = any(  # This will match as soon as a new version matches
        f"{major}.{minor}.{patch}" in specifier
        for major in range(5, 10)
        for minor in range(20)
        for patch in range(50)
    )
    return not new_releases_match


def generate_args(*, source_files: SourceFiles, isort: Isort, check_only: bool) -> Tuple[str, ...]:
    # NB: isort auto-discovers config files in versions <5. Only for isort>=5 we need to hardcode them via command line
    # flags.
    args = []

    if isort.config:
        # We don't really expect users of isort<4
        if len(isort.config) >= 2:
            logger.warning(
                "Found more than one config file for isort, taking the last one (%s) since isort uses a single config"
                "file: the last one provided. For more, customization, set [isort].args.",
                isort.config[-1],
            )
        if isort.version is None or not is_old_isort_version(isort.version):  # isort>=5
            args.append(f"--settings-path={isort.config[-1]}")
    if check_only:
        args.append("--check-only")
    args.extend(isort.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def setup_isort(setup_request: SetupRequest, isort: Isort) -> Setup:
    isort_pex_request = Get(
        Pex,
        PexRequest(
            output_filename="isort.pex",
            internal_only=True,
            requirements=PexRequirements(isort.all_requirements),
            interpreter_constraints=PexInterpreterConstraints(isort.interpreter_constraints),
            entry_point=isort.entry_point,
        ),
    )

    config_digest_request = Get(
        Digest,
        PathGlobs(
            globs=isort.config,
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            conjunction=GlobExpansionConjunction.all_match,
            description_of_origin="the option `--isort-config`",
        ),
    )

    source_files_request = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets),
    )

    source_files, isort_pex, config_digest = await MultiGet(
        source_files_request, isort_pex_request, config_digest_request
    )
    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    input_digest = await Get(
        Digest,
        MergeDigests((source_files_snapshot.digest, isort_pex.digest, config_digest)),
    )

    process = await Get(
        Process,
        PexProcess(
            isort_pex,
            argv=generate_args(
                source_files=source_files, isort=isort, check_only=setup_request.check_only
            ),
            input_digest=input_digest,
            output_files=source_files_snapshot.files,
            description=f"Run isort on {pluralize(len(setup_request.request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with isort", level=LogLevel.DEBUG)
async def isort_fmt(request: IsortRequest, isort: Isort) -> FmtResult:
    if isort.skip:
        return FmtResult.skip(formatter_name="isort")
    setup = await Get(Setup, SetupRequest(request, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result,
        original_digest=setup.original_digest,
        formatter_name="isort",
        strip_chroot_path=True,
    )


@rule(desc="Lint with isort", level=LogLevel.DEBUG)
async def isort_lint(request: IsortRequest, isort: Isort) -> LintResults:
    if isort.skip:
        return LintResults([], linter_name="isort")
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return LintResults(
        [LintResult.from_fallible_process_result(result, strip_chroot_path=True)],
        linter_name="isort",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PythonFmtRequest, IsortRequest),
        UnionRule(LintRequest, IsortRequest),
        *pex.rules(),
        *stripped_source_files.rules(),
    ]
