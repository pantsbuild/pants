# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.bandit.subsystem import Bandit
from pants.backend.python.rules import pex
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.target_types import PythonInterpreterCompatibility, PythonSources
from pants.core.goals.lint import (
    LintRequest,
    LintResult,
    LintResults,
    LintSubsystem,
    extract_lint_report,
)
from pants.core.util_rules import source_files, stripped_source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, GlobMatchErrorBehavior, MergeDigests, PathGlobs
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class BanditFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources
    compatibility: PythonInterpreterCompatibility


class BanditRequest(LintRequest):
    field_set_type = BanditFieldSet


@dataclass(frozen=True)
class BanditPartition:
    field_sets: Tuple[BanditFieldSet, ...]
    interpreter_constraints: PexInterpreterConstraints


def generate_args(
    *, source_files: SourceFiles, bandit: Bandit, report_file_name: Optional[str]
) -> Tuple[str, ...]:
    args = []
    if bandit.config is not None:
        args.append(f"--config={bandit.config}")
    if report_file_name:
        args.append(f"--output={report_file_name}")
    args.extend(bandit.args)
    args.extend(source_files.files)
    return tuple(args)


@rule
async def bandit_lint_partition(
    partition: BanditPartition, bandit: Bandit, lint_subsystem: LintSubsystem
) -> LintResult:
    requirements_pex_request = Get(
        Pex,
        PexRequest(
            output_filename="bandit.pex",
            internal_only=True,
            requirements=PexRequirements(bandit.all_requirements),
            interpreter_constraints=(
                partition.interpreter_constraints
                or PexInterpreterConstraints(bandit.interpreter_constraints)
            ),
            entry_point=bandit.entry_point,
        ),
    )

    config_digest_request = Get(
        Digest,
        PathGlobs(
            globs=[bandit.config] if bandit.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--bandit-config`",
        ),
    )

    source_files_request = Get(
        SourceFiles, SourceFilesRequest(field_set.sources for field_set in partition.field_sets)
    )

    requirements_pex, config_digest, source_files = await MultiGet(
        requirements_pex_request, config_digest_request, source_files_request
    )

    input_digest = await Get(
        Digest, MergeDigests((source_files.snapshot.digest, requirements_pex.digest, config_digest))
    )

    report_file_name = "bandit_report.txt" if lint_subsystem.reports_dir else None

    result = await Get(
        FallibleProcessResult,
        PexProcess(
            requirements_pex,
            argv=generate_args(
                source_files=source_files, bandit=bandit, report_file_name=report_file_name
            ),
            input_digest=input_digest,
            description=f"Run Bandit on {pluralize(len(partition.field_sets), 'file')}.",
            output_files=(report_file_name,) if report_file_name else None,
            level=LogLevel.DEBUG,
        ),
    )
    report = await extract_lint_report("Bandit", result, report_file_name)
    return LintResult.from_fallible_process_result(
        result, partition_description=str(sorted(partition.interpreter_constraints)), report=report
    )


@rule(desc="Lint with Bandit")
async def bandit_lint(
    request: BanditRequest, bandit: Bandit, python_setup: PythonSetup
) -> LintResults:
    if bandit.skip:
        return LintResults([], linter_name="Bandit")

    # NB: Bandit output depends upon which Python interpreter version it's run with
    # ( https://github.com/PyCQA/bandit#under-which-version-of-python-should-i-install-bandit). We
    # batch targets by their constraints to ensure, for example, that all Python 2 targets run
    # together and all Python 3 targets run together.
    constraints_to_field_sets = PexInterpreterConstraints.group_field_sets_by_constraints(
        request.field_sets, python_setup
    )
    partitioned_results = await MultiGet(
        Get(LintResult, BanditPartition(partition_field_sets, partition_compatibility))
        for partition_compatibility, partition_field_sets in constraints_to_field_sets.items()
    )
    return LintResults(partitioned_results, linter_name="Bandit")


def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, BanditRequest),
        *pex.rules(),
        *source_files.rules(),
        *stripped_source_files.rules(),
    ]
