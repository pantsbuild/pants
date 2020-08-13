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
from pants.core.goals.lint import LintReport, LintRequest, LintResult, LintResults, LintSubsystem
from pants.core.util_rules import source_files, stripped_source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import (
    Digest,
    DigestSubset,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
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

    address_references = ", ".join(
        sorted(field_set.address.spec for field_set in partition.field_sets)
    )
    report_file_name = "bandit_report.txt" if lint_subsystem.reports_dir else None
    args = generate_args(
        source_files=source_files, bandit=bandit, report_file_name=report_file_name
    )

    result = await Get(
        FallibleProcessResult,
        PexProcess(
            requirements_pex,
            argv=args,
            input_digest=input_digest,
            description=(
                f"Run Bandit on {pluralize(len(partition.field_sets), 'target')}: "
                f"{address_references}."
            ),
            output_files=(report_file_name,) if report_file_name else None,
        ),
    )

    report = None
    if report_file_name:
        report_digest = await Get(
            Digest,
            DigestSubset(
                result.output_digest,
                PathGlobs(
                    [report_file_name],
                    glob_match_error_behavior=GlobMatchErrorBehavior.warn,
                    description_of_origin="Bandit report file",
                ),
            ),
        )
        report = LintReport(report_file_name, report_digest)

    return LintResult.from_fallible_process_result(result, linter_name="Bandit", report=report)


@rule(desc="Lint using Bandit")
async def bandit_lint(
    request: BanditRequest, bandit: Bandit, python_setup: PythonSetup
) -> LintResults:
    if bandit.skip:
        return LintResults()

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
    return LintResults(partitioned_results)


def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, BanditRequest),
        *pex.rules(),
        *source_files.rules(),
        *stripped_source_files.rules(),
    ]
