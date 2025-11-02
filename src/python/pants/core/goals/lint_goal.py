# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from typing import TypeVar

from pants.base.specs import Specs
from pants.core.goals.fix import AbstractFixRequest, convert_fix_result_to_lint_result, fix_batch
from pants.core.goals.lint import (
    AbstractLintRequest,
    Lint,
    LintFilesRequest,
    LintResult,
    LintSubsystem,
    LintTargetsRequest,
    get_partitions_by_request_type,
    lint_batch,
    partition_files,
    partition_targets,
)
from pants.core.goals.multi_tool_goal_helper import write_reports
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import PathGlobs, Workspace
from pants.engine.intrinsics import digest_to_snapshot
from pants.engine.rules import collect_rules, concurrently, goal_rule, implicitly, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionMembership
from pants.util.collections import partition_sequentially
from pants.util.docutil import bin_name

logger = logging.getLogger(__name__)


_T = TypeVar("_T")


def _print_results(
    console: Console,
    results_by_tool: dict[str, list[LintResult]],
    formatter_failed: bool,
    fixer_failed: bool,
) -> None:
    if results_by_tool:
        console.print_stderr("")

    for tool_name in sorted(results_by_tool):
        results = results_by_tool[tool_name]
        if any(result.exit_code for result in results):
            sigil = console.sigil_failed()
            status = "failed"
        else:
            sigil = console.sigil_succeeded()
            status = "succeeded"
        console.print_stderr(f"{sigil} {tool_name} {status}.")

    if formatter_failed or fixer_failed:
        console.print_stderr("")

    if formatter_failed:
        console.print_stderr(f"(One or more formatters failed. Run `{bin_name()} fmt` to fix.)")

    if fixer_failed:
        console.print_stderr(f"(One or more fixers failed. Run `{bin_name()} fix` to fix.)")


def _get_error_code(results: Sequence[LintResult]) -> int:
    for result in reversed(results):
        if result.exit_code:
            return result.exit_code
    return 0


@rule
async def run_fixer_or_formatter_as_linter(batch: AbstractFixRequest.Batch) -> LintResult:
    # Note that AbstractFixRequest has AbstractFmtResult as a subtype (even though this doesn't
    # seem to make sense semantically), and fix_batch() operates on both.
    # TODO: Untangle, or at least make sense of, the complicated subtype relationships
    #  governing lint/fmt/fix, and document them. They are currently very hard to grok.
    #  See https://github.com/pantsbuild/pants/issues/22536.
    fix_result = await fix_batch(**implicitly({batch: AbstractFixRequest.Batch}))
    lint_result = await convert_fix_result_to_lint_result(fix_result)
    return lint_result


@goal_rule
async def lint(
    console: Console,
    workspace: Workspace,
    specs: Specs,
    lint_subsystem: LintSubsystem,
    union_membership: UnionMembership,
    dist_dir: DistDir,
) -> Lint:
    lint_request_types = union_membership.get(AbstractLintRequest)
    target_partitioners = union_membership.get(LintTargetsRequest.PartitionRequest)
    file_partitioners = union_membership.get(LintFilesRequest.PartitionRequest)

    partitions_by_request_type = await get_partitions_by_request_type(
        [
            request_type
            for request_type in lint_request_types
            if not (request_type.is_formatter and lint_subsystem.skip_formatters)
            and not (request_type.is_fixer and lint_subsystem.skip_fixers)
        ],
        target_partitioners,
        file_partitioners,
        lint_subsystem,  # type: ignore[arg-type]
        specs,
        lambda request_type: partition_targets(
            **implicitly({request_type: LintTargetsRequest.PartitionRequest})
        ),
        lambda request_type: partition_files(
            **implicitly({request_type: LintFilesRequest.PartitionRequest})
        ),
    )

    if not partitions_by_request_type:
        return Lint(exit_code=0)

    def batch_by_size(iterable: Iterable[_T]) -> Iterator[tuple[_T, ...]]:
        batches = partition_sequentially(
            iterable,
            key=lambda x: str(x.address) if isinstance(x, FieldSet) else str(x),
            size_target=lint_subsystem.batch_size,
            size_max=4 * lint_subsystem.batch_size,
        )
        for batch in batches:
            yield tuple(batch)

    lint_batches_by_request_type = {
        request_type: [
            (batch, partition.metadata)
            for partitions in partitions_list
            for partition in partitions
            for batch in batch_by_size(partition.elements)
        ]
        for request_type, partitions_list in partitions_by_request_type.items()
    }

    formatter_snapshots = await concurrently(
        digest_to_snapshot(**implicitly({PathGlobs(elements): PathGlobs}))
        for request_type, batch in lint_batches_by_request_type.items()
        for elements, _ in batch
        if request_type._requires_snapshot
    )
    snapshots_iter = iter(formatter_snapshots)

    # Pairs of (batch, whether the batch is a fixer/formatter running as a linter).
    # In this context "running as a linter" means that we run it on a temp copy of the
    # files and diff the output to see if it passes or fails, without modifying the
    # original files. We may do this even when the fixer/formatter has a read-only lint
    # mode, so that, when the user requests the fix/fmt and lint goals, we don't have to run the
    # tool twice, once with read-only flags and once with "edit the files" flags.
    batches: Iterable[tuple[AbstractLintRequest.Batch, bool]] = [
        (
            request_type.Batch(
                request_type.tool_name,
                elements,
                key,
                **{"snapshot": next(snapshots_iter)} if request_type._requires_snapshot else {},
            ),
            request_type.is_fixer or request_type.is_formatter,
        )
        for request_type, batch in lint_batches_by_request_type.items()
        for elements, key in batch
    ]

    all_batch_results = await concurrently(
        [
            run_fixer_or_formatter_as_linter(batch)  # type:ignore[arg-type]
            if is_fixer_or_formatter
            else lint_batch(**implicitly({batch: AbstractLintRequest.Batch}))
            for batch, is_fixer_or_formatter in batches
        ]
    )

    core_request_types_by_batch_type = {
        request_type.Batch: request_type for request_type in lint_request_types
    }

    formatter_failed = any(
        result.exit_code
        for (batch, _), result in zip(batches, all_batch_results)
        if core_request_types_by_batch_type[type(batch)].is_formatter
    )

    fixer_failed = any(
        result.exit_code
        for (batch, _), result in zip(batches, all_batch_results)
        if core_request_types_by_batch_type[type(batch)].is_fixer
    )

    results_by_tool = defaultdict(list)
    for result in all_batch_results:
        results_by_tool[result.linter_name].append(result)

    write_reports(
        results_by_tool,
        workspace,
        dist_dir,
        goal_name=LintSubsystem.name,
    )

    _print_results(
        console,
        results_by_tool,
        formatter_failed,
        fixer_failed,
    )
    return Lint(_get_error_code(all_batch_results))


def rules():
    return collect_rules()
