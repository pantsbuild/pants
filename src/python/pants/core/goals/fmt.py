# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, NamedTuple, Sequence, Tuple, Type, TypeVar

from pants.base.specs import Specs
from pants.core.goals.lint import LintFilesRequest, LintRequest, LintResult, LintTargetsRequest
from pants.core.goals.lint import Partitions as LintPartitions
from pants.core.goals.lint import _get_partitions_by_request_type
from pants.core.goals.style_request import only_option_help, style_batch_size_help
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest, MergeDigests, PathGlobs, Snapshot, SnapshotDiff, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule, rule_helper
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.option.option_types import IntOption, StrListOption
from pants.util.collections import partition_sequentially
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init, runtime_ignore_subscripts
from pants.util.strutil import strip_v2_chroot_path

_F = TypeVar("_F", bound="FmtResult")
_T = TypeVar("_T")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FmtResult(EngineAwareReturnType):
    input: Snapshot
    output: Snapshot
    stdout: str
    stderr: str
    formatter_name: str

    @classmethod
    def create(
        cls,
        process_result: ProcessResult | FallibleProcessResult,
        input_snapshot: Snapshot,
        output: Snapshot,
        *,
        formatter_name: str,
        strip_chroot_path: bool = False,
    ) -> FmtResult:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return cls(
            input=input_snapshot,
            output=output,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            formatter_name=formatter_name,
        )

    def __post_init__(self):
        # NB: We debug log stdout/stderr because `message` doesn't log it.
        log = f"Output from {self.formatter_name}"
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
        #   1. This is run as part of both `fmt` and `lint`, and we want consistent output between both
        #   2. Different formatters have different stdout/stderr. This way is consistent across all
        #       formatters.
        # We also allow added/removed files because the `fmt` goal is more like a `fix` goal.
        # (See https://github.com/pantsbuild/pants/issues/13504)
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

        return f"{self.formatter_name} {message}{output}"

    def cacheable(self) -> bool:
        """Is marked uncacheable to ensure that it always renders."""
        return False


Partitions = LintPartitions[str]


@union
class FmtRequest(LintRequest):
    is_formatter = True

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    @runtime_ignore_subscripts
    @frozen_after_init
    @dataclass(unsafe_hash=True)
    class SubPartition(LintRequest.SubPartition):
        snapshot: Snapshot

        @property
        def files(self) -> tuple[str, ...]:
            return self.elements

    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_registration_rules()
        yield UnionRule(FmtRequest, cls)
        yield UnionRule(FmtRequest.SubPartition, cls.SubPartition)


class FmtTargetsRequest(FmtRequest, LintTargetsRequest):
    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_registration_rules()
        yield UnionRule(FmtTargetsRequest.PartitionRequest, cls.PartitionRequest)


class FmtFilesRequest(FmtRequest, LintFilesRequest):
    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_registration_rules()
        yield UnionRule(FmtFilesRequest.PartitionRequest, cls.PartitionRequest)


class _FmtSubpartitionBatchElement(NamedTuple):
    request_type: type[FmtRequest.SubPartition]
    files: tuple[str, ...]
    key: Any


class _FmtSubpartitionBatchRequest(Collection[_FmtSubpartitionBatchElement]):
    """Request to serially format all the subpartitions in the given batch."""


@dataclass(frozen=True)
class _FmtBatchResult:
    results: tuple[FmtResult, ...]

    @property
    def did_change(self) -> bool:
        return any(result.did_change for result in self.results)


class FmtSubsystem(GoalSubsystem):
    name = "fmt"
    help = "Autoformat source code."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return FmtRequest in union_membership

    only = StrListOption(
        help=only_option_help("fmt", "formatter", "isort", "shfmt"),
    )
    batch_size = IntOption(
        advanced=True,
        default=128,
        help=style_batch_size_help(uppercase="Formatter", lowercase="formatter"),
    )


class Fmt(Goal):
    subsystem_cls = FmtSubsystem


@rule_helper
async def _write_files(workspace: Workspace, batched_results: Iterable[_FmtBatchResult]):
    if any(batched_result.did_change for batched_result in batched_results):
        # NB: this will fail if there are any conflicting changes, which we want to happen rather
        # than silently having one result override the other. In practice, this should never
        # happen due to us grouping each file's formatters into a single digest.
        merged_formatted_digest = await Get(
            Digest,
            MergeDigests(
                batched_result.results[-1].output.digest for batched_result in batched_results
            ),
        )
        workspace.write_digest(merged_formatted_digest)


def _print_results(
    console: Console,
    results: Iterable[FmtResult],
):
    if results:
        console.print_stderr("")

    # We group all results for the same formatter so that we can give one final status in the
    # summary. This is only relevant if there were multiple results because of
    # `--per-file-caching`.
    formatter_to_results = defaultdict(set)
    for result in results:
        formatter_to_results[result.formatter_name].add(result)

    for formatter, results in sorted(formatter_to_results.items()):
        if any(result.did_change for result in results):
            sigil = console.sigil_succeeded_with_edits()
            status = "made changes"
        else:
            sigil = console.sigil_succeeded()
            status = "made no changes"
        console.print_stderr(f"{sigil} {formatter} {status}.")


@goal_rule
async def fmt(
    console: Console,
    specs: Specs,
    fmt_subsystem: FmtSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    fmt_request_types = list(union_membership.get(FmtRequest))
    target_partitioners = list(union_membership.get(FmtTargetsRequest.PartitionRequest))
    file_partitioners = list(union_membership.get(FmtFilesRequest.PartitionRequest))

    partitions_by_request_type = await _get_partitions_by_request_type(
        fmt_request_types,
        target_partitioners,
        file_partitioners,
        fmt_subsystem,
        specs,
        lambda request_type: Get(Partitions, FmtTargetsRequest.PartitionRequest, request_type),
        lambda request_type: Get(Partitions, FmtFilesRequest.PartitionRequest, request_type),
    )

    if not partitions_by_request_type:
        return Fmt(exit_code=0)

    def batch(files: Iterable[str]) -> Iterator[tuple[str, ...]]:
        batches = partition_sequentially(
            files,
            key=lambda x: str(x),
            size_target=fmt_subsystem.batch_size,
            size_max=4 * fmt_subsystem.batch_size,
        )
        for batch in batches:
            yield tuple(batch)

    def _make_disjoint_subpartition_batch_requests() -> Iterable[_FmtSubpartitionBatchRequest]:
        partition_infos: Sequence[Tuple[Type[FmtRequest], Any]]
        files: Sequence[str]

        partition_infos_by_files = defaultdict(list)
        for request_type, partitions_list in partitions_by_request_type.items():
            for partitions in partitions_list:
                for key, files in partitions.items():
                    for file in files:
                        partition_infos_by_files[file].append((request_type, key))

        files_by_partition_info = defaultdict(list)
        for file, partition_infos in partition_infos_by_files.items():
            files_by_partition_info[tuple(partition_infos)].append(file)

        for partition_infos, files in files_by_partition_info.items():
            for subpartition in batch(files):
                yield _FmtSubpartitionBatchRequest(
                    _FmtSubpartitionBatchElement(
                        request_type.SubPartition, subpartition, partition_key
                    )
                    for request_type, partition_key in partition_infos
                )

    all_results = await MultiGet(
        Get(_FmtBatchResult, _FmtSubpartitionBatchRequest, request)
        for request in _make_disjoint_subpartition_batch_requests()
    )

    individual_results = list(
        itertools.chain.from_iterable(result.results for result in all_results)
    )

    await _write_files(workspace, all_results)
    _print_results(console, individual_results)

    # Since the rules to produce FmtResult should use ExecuteRequest, rather than
    # FallibleProcess, we assume that there were no failures.
    return Fmt(exit_code=0)


@rule
async def fmt_batch(
    request: _FmtSubpartitionBatchRequest,
) -> _FmtBatchResult:
    current_snapshot = await Get(Snapshot, PathGlobs(request[0].files))

    results = []
    for request_type, files, key in request:
        subpartition = request_type(files, key, current_snapshot)
        result = await Get(FmtResult, FmtRequest.SubPartition, subpartition)
        results.append(result)

        assert set(result.output.files) == set(
            subpartition.files
        ), f"Expected {result.output.files} to match {subpartition.files}"
        current_snapshot = result.output
    return _FmtBatchResult(tuple(results))


@rule(level=LogLevel.DEBUG)
async def convert_fmt_result_to_lint_result(fmt_result: FmtResult) -> LintResult:
    return LintResult(
        1 if fmt_result.did_change else 0,
        fmt_result.stdout,
        fmt_result.stderr,
        linter_name=fmt_result.formatter_name,
    )


def rules():
    return collect_rules()
