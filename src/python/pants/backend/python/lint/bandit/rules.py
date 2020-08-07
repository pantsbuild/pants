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
    LintResultFile,
    LintResults,
    LintSubsystem,
)
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.core.util_rules.determine_source_files import SourceFiles, SourceFilesRequest
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
    *, source_files: SourceFiles, bandit: Bandit, output_file: Optional[str]
) -> Tuple[str, ...]:
    args = []
    if bandit.config is not None:
        args.append(f"--config={bandit.config}")
    if output_file:
        args.append(f"--output={output_file}")
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

    address_references = ", ".join(
        sorted(field_set.address.spec for field_set in partition.field_sets)
    )
    report_path = (
        lint_subsystem.reports_dir / "bandit_report.txt" if lint_subsystem.reports_dir else None
    )
    args = generate_args(
        source_files=source_files,
        bandit=bandit,
        output_file=report_path.name if report_path else None,
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
            output_files=(report_path.name,) if report_path else None,
        ),
    )

    results_file = None
    if report_path:
        report_file_snapshot = await Get(
            Snapshot, DigestSubset(result.output_digest, PathGlobs([report_path.name]))
        )
        if len(report_file_snapshot.files) != 1:
            raise Exception(f"Unexpected report file snapshot: {report_file_snapshot.files}")
        results_file = LintResultFile(output_path=report_path, digest=report_file_snapshot.digest)

    return LintResult.from_fallible_process_result(
        result, linter_name="Bandit", results_file=results_file
    )


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
        *determine_source_files.rules(),
        *pex.rules(),
        *strip_source_roots.rules(),
    ]
