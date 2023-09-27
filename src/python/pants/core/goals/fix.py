# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, NamedTuple, Sequence, Tuple, Type, TypeVar

from typing_extensions import Protocol

from pants.base.specs import Specs
from pants.core.goals.lint import (
    AbstractLintRequest,
    LintFilesRequest,
    LintResult,
    LintTargetsRequest,
    _get_partitions_by_request_type,
    _MultiToolGoalSubsystem,
)
from pants.core.goals.multi_tool_goal_helper import BatchSizeOption, OnlyOption
from pants.core.util_rules.partitions import PartitionerType, PartitionMetadataT
from pants.core.util_rules.partitions import Partitions as UntypedPartitions
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest, MergeDigests, PathGlobs, Snapshot, SnapshotDiff, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.option.option_types import BoolOption
from pants.util.collections import partition_sequentially
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import Simplifier, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FixResult(EngineAwareReturnType):
    input: Snapshot
    output: Snapshot
    stdout: str
    stderr: str
    tool_name: str

    @staticmethod
    async def create(
        request: AbstractFixRequest.Batch,
        process_result: ProcessResult | FallibleProcessResult,
        *,
        output_simplifier: Simplifier = Simplifier(),
    ) -> FixResult:
        return FixResult(
            input=request.snapshot,
            output=await Get(Snapshot, Digest, process_result.output_digest),
            stdout=output_simplifier.simplify(process_result.stdout),
            stderr=output_simplifier.simplify(process_result.stderr),
            tool_name=request.tool_name,
        )

    def __post_init__(self):
        # NB: We debug log stdout/stderr because `message` doesn't log it.
        log = f"Output from {self.tool_name}"
        if self.stdout:
            log += f"\n{self.stdout}"
        if self.stderr:
            log += f"\n{self.stderr}"
        logger.debug(log)

    @property
    def did_change(self) -> bool:
        return self.output != self.input

    def level(self) -> LogLevel | None:
        return LogLevel.WARN if self.did_change else LogLevel.INFO

    def message(self) -> str | None:
        message = "made changes." if self.did_change else "made no changes."

        # NB: Instead of printing out `stdout` and `stderr`, we just print a list of files which
        # were changed/added/removed. We do this for two reasons:
        #   1. This is run as part of both `fmt`/`fix` and `lint`, and we want consistent output between both
        #   2. Different tools have different stdout/stderr. This way is consistent across all tools.
        if self.did_change:
            snapshot_diff = SnapshotDiff.from_snapshots(self.input, self.output)
            output = "".join(
                f"\n  {file}"
                for file in itertools.chain(
                    snapshot_diff.changed_files,
                    snapshot_diff.their_unique_files,  # added files
                    snapshot_diff.our_unique_files,  # removed files
                    # NB: there is no rename detection, so a renames will list
                    # both the old filename (removed) and the new filename (added).
                )
            )
        else:
            output = ""

        return f"{self.tool_name} {message}{output}"

    def cacheable(self) -> bool:
        """Is marked uncacheable to ensure that it always renders."""
        return False


Partitions = UntypedPartitions[str, PartitionMetadataT]


@union
class AbstractFixRequest(AbstractLintRequest):
    is_fixer = True

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    @dataclass(frozen=True)
    class Batch(AbstractLintRequest.Batch):
        snapshot: Snapshot

        @property
        def files(self) -> tuple[str, ...]:
            return tuple(FrozenOrderedSet(self.elements))

    @classmethod
    def _get_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_rules()
        yield UnionRule(AbstractFixRequest, cls)
        yield UnionRule(AbstractFixRequest.Batch, cls.Batch)


class FixTargetsRequest(AbstractFixRequest, LintTargetsRequest):
    @classmethod
    def _get_rules(cls) -> Iterable:
        yield from cls.partitioner_type.default_rules(cls, by_file=True)
        yield from (
            rule
            for rule in super()._get_rules()
            # NB: We don't want to yield `lint.py`'s default partitioner
            if isinstance(rule, UnionRule)
        )
        yield UnionRule(FixTargetsRequest.PartitionRequest, cls.PartitionRequest)


class FixFilesRequest(AbstractFixRequest, LintFilesRequest):
    @classmethod
    def _get_rules(cls) -> Iterable:
        if cls.partitioner_type is not PartitionerType.CUSTOM:
            raise ValueError(
                "Pants does not provide default partitioners for `FixFilesRequest`."
                + " You will need to provide your own partitioner rule."
            )

        yield from super()._get_rules()
        yield UnionRule(FixFilesRequest.PartitionRequest, cls.PartitionRequest)


class _FixBatchElement(NamedTuple):
    request_type: type[AbstractFixRequest.Batch]
    tool_name: str
    files: tuple[str, ...]
    key: Any


class _FixBatchRequest(Collection[_FixBatchElement]):
    """Request to serially fix all the elements in the given batch."""


@dataclass(frozen=True)
class _FixBatchResult:
    results: tuple[FixResult, ...]

    @property
    def did_change(self) -> bool:
        return any(result.did_change for result in self.results)


class FixSubsystem(GoalSubsystem):
    name = "fix"
    help = "Autofix source code."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return AbstractFixRequest in union_membership

    only = OnlyOption("fixer", "autoflake", "pyupgrade")
    skip_formatters = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, skip running all formatters.

            FYI: when running `{bin_name()} fix fmt ::`, there should be diminishing performance
            benefit to using this flag. Pants attempts to reuse the results from `fmt` when running
            `fix` where possible.
            """
        ),
    )
    batch_size = BatchSizeOption(uppercase="Fixer", lowercase="fixer")


class Fix(Goal):
    subsystem_cls = FixSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


async def _write_files(workspace: Workspace, batched_results: Iterable[_FixBatchResult]):
    if any(batched_result.did_change for batched_result in batched_results):
        # NB: this will fail if there are any conflicting changes, which we want to happen rather
        # than silently having one result override the other. In practice, this should never
        # happen due to us grouping each file's tools into a single digest.
        merged_digest = await Get(
            Digest,
            MergeDigests(
                batched_result.results[-1].output.digest for batched_result in batched_results
            ),
        )
        workspace.write_digest(merged_digest)


def _print_results(
    console: Console,
    results: Iterable[FixResult],
):
    if results:
        console.print_stderr("")

    # We group all results for the same tool so that we can give one final status in the
    # summary. This is only relevant if there were multiple results because of
    # `--per-file-caching`.
    tool_to_results = defaultdict(set)
    for result in results:
        tool_to_results[result.tool_name].add(result)

    for tool, results in sorted(tool_to_results.items()):
        if any(result.did_change for result in results):
            sigil = console.sigil_succeeded_with_edits()
            status = "made changes"
        else:
            sigil = console.sigil_succeeded()
            status = "made no changes"
        console.print_stderr(f"{sigil} {tool} {status}.")


_CoreRequestType = TypeVar("_CoreRequestType", bound=AbstractFixRequest)
_TargetPartitioner = TypeVar("_TargetPartitioner", bound=FixTargetsRequest.PartitionRequest)
_FilePartitioner = TypeVar("_FilePartitioner", bound=FixFilesRequest.PartitionRequest)
_GoalT = TypeVar("_GoalT", bound=Goal)


class _BatchableMultiToolGoalSubsystem(_MultiToolGoalSubsystem, Protocol):
    batch_size: BatchSizeOption


async def _do_fix(
    core_request_types: Iterable[type[_CoreRequestType]],
    target_partitioners: Iterable[type[_TargetPartitioner]],
    file_partitioners: Iterable[type[_FilePartitioner]],
    goal_cls: type[_GoalT],
    subsystem: _BatchableMultiToolGoalSubsystem,
    specs: Specs,
    workspace: Workspace,
    console: Console,
    make_targets_partition_request_get: Callable[[_TargetPartitioner], Get[Partitions]],
    make_files_partition_request_get: Callable[[_FilePartitioner], Get[Partitions]],
) -> _GoalT:
    partitions_by_request_type = await _get_partitions_by_request_type(
        core_request_types,
        target_partitioners,
        file_partitioners,
        subsystem,
        specs,
        make_targets_partition_request_get,
        make_files_partition_request_get,
    )

    if not partitions_by_request_type:
        return goal_cls(exit_code=0)

    def batch_by_size(files: Iterable[str]) -> Iterator[tuple[str, ...]]:
        batches = partition_sequentially(
            files,
            key=lambda x: str(x),
            size_target=subsystem.batch_size,
            size_max=4 * subsystem.batch_size,
        )
        for batch in batches:
            yield tuple(batch)

    def _make_disjoint_batch_requests() -> Iterable[_FixBatchRequest]:
        partition_infos: Iterable[Tuple[Type[AbstractFixRequest], Any]]
        files: Sequence[str]

        partition_infos_by_files = defaultdict(list)
        for request_type, partitions_list in partitions_by_request_type.items():
            for partitions in partitions_list:
                for partition in partitions:
                    for file in partition.elements:
                        partition_infos_by_files[file].append((request_type, partition.metadata))

        files_by_partition_info = defaultdict(list)
        for file, partition_infos in partition_infos_by_files.items():
            deduped_partition_infos = FrozenOrderedSet(partition_infos)
            files_by_partition_info[deduped_partition_infos].append(file)

        for partition_infos, files in files_by_partition_info.items():
            for batch in batch_by_size(files):
                yield _FixBatchRequest(
                    _FixBatchElement(
                        request_type.Batch,
                        request_type.tool_name,
                        batch,
                        partition_metadata,
                    )
                    for request_type, partition_metadata in partition_infos
                )

    all_results = await MultiGet(
        Get(_FixBatchResult, _FixBatchRequest, request)
        for request in _make_disjoint_batch_requests()
    )

    individual_results = list(
        itertools.chain.from_iterable(result.results for result in all_results)
    )

    await _write_files(workspace, all_results)
    _print_results(console, individual_results)

    # Since the rules to produce FixResult should use ProcessResult, rather than
    # FallibleProcessResult, we assume that there were no failures.
    return goal_cls(exit_code=0)


@goal_rule
async def fix(
    console: Console,
    specs: Specs,
    fix_subsystem: FixSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fix:
    return await _do_fix(
        sorted(
            (
                request_type
                for request_type in union_membership.get(AbstractFixRequest)
                if not (request_type.is_formatter and fix_subsystem.skip_formatters)
            ),
            # NB: We sort the core request types so that fixers are first. This is to ensure that, between
            # fixers and formatters, re-running isn't necessary due to tool conflicts (re-running may
            # still be necessary within formatters). This is because fixers are expected to modify
            # code irrespective of formattint, and formatters aren't expected to be modifying the code
            # in a way that needs to be fixed.
            key=lambda request_type: request_type.is_fixer,
            reverse=True,
        ),
        union_membership.get(FixTargetsRequest.PartitionRequest),
        union_membership.get(FixFilesRequest.PartitionRequest),
        Fix,
        fix_subsystem,
        specs,
        workspace,
        console,
        lambda request_type: Get(Partitions, FixTargetsRequest.PartitionRequest, request_type),
        lambda request_type: Get(Partitions, FixFilesRequest.PartitionRequest, request_type),
    )


@rule
async def fix_batch(
    request: _FixBatchRequest,
) -> _FixBatchResult:
    current_snapshot = await Get(Snapshot, PathGlobs(request[0].files))

    results = []
    for request_type, tool_name, files, key in request:
        batch = request_type(tool_name, files, key, current_snapshot)
        result = await Get(  # noqa: PNT30: this is inherently sequential
            FixResult, AbstractFixRequest.Batch, batch
        )
        results.append(result)

        assert set(result.output.files) == set(
            batch.files
        ), f"Expected {result.output.files} to match {batch.files}"
        current_snapshot = result.output
    return _FixBatchResult(tuple(results))


@rule(level=LogLevel.DEBUG)
async def convert_fix_result_to_lint_result(fix_result: FixResult) -> LintResult:
    return LintResult(
        1 if fix_result.did_change else 0,
        fix_result.stdout,
        fix_result.stderr,
        linter_name=fix_result.tool_name,
        _render_message=False,  # Don't re-render the message
    )


def rules():
    return collect_rules()
