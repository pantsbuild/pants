# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, TypeVar

from pants.core.goals.style_request import (
    StyleRequest,
    determine_specified_tool_names,
    only_option_help,
    style_batch_size_help,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import Digest, MergeDigests, Snapshot, SnapshotDiff, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import EMPTY_SNAPSHOT
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule, rule_helper
from pants.engine.target import FieldSet, FilteredTargets, SourcesField, Target, Targets
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import IntOption, StrListOption
from pants.util.collections import partition_sequentially
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import strip_v2_chroot_path

_F = TypeVar("_F", bound="FmtResult")
_FS = TypeVar("_FS", bound=FieldSet)
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
        request: FmtTargetsRequest,
        process_result: ProcessResult | FallibleProcessResult,
        output: Snapshot,
        *,
        strip_chroot_path: bool = False,
    ) -> FmtResult:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return cls(
            input=request.snapshot,
            output=output,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            formatter_name=request.name,
        )

    def __post_init__(self):
        # NB: We debug log stdout/stderr because `message` doesn't log it.
        log = f"Output from {self.formatter_name}"
        if self.stdout:
            log += f"\n{self.stdout}"
        if self.stderr:
            log += f"\n{self.stderr}"
        logger.debug(log)

    @classmethod
    def skip(cls: type[_F], *, formatter_name: str) -> _F:
        return cls(
            input=EMPTY_SNAPSHOT,
            output=EMPTY_SNAPSHOT,
            stdout="",
            stderr="",
            formatter_name=formatter_name,
        )

    @property
    def skipped(self) -> bool:
        return (
            self.input == EMPTY_SNAPSHOT
            and self.output == EMPTY_SNAPSHOT
            and not self.stdout
            and not self.stderr
        )

    @property
    def did_change(self) -> bool:
        return self.output != self.input

    def level(self) -> LogLevel | None:
        if self.skipped:
            return LogLevel.DEBUG
        return LogLevel.WARN if self.did_change else LogLevel.INFO

    def message(self) -> str | None:
        if self.skipped:
            return f"{self.formatter_name} skipped."
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


@union
@frozen_after_init
@dataclass(unsafe_hash=True)
class FmtTargetsRequest(StyleRequest[_FS]):
    snapshot: Snapshot

    def __init__(self, field_sets: Iterable[_FS], snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        super().__init__(field_sets)


@dataclass(frozen=True)
class _FmtTargetBatchRequest:
    """Format all the targets in the given batch.

    NOTE: Several requests can be made in parallel (via `MultiGet`) iff the target batches are
        non-overlapping. Within the request, the FmtTargetsRequests will be issued sequentially
        with the result of each run fed into the next run. To maximize parallel performance, the
        targets in a batch should share a FieldSet.
    """

    request_types: tuple[type[FmtTargetsRequest], ...]
    targets: Targets


@dataclass(frozen=True)
class _FmtBatchResult:
    results: tuple[FmtResult, ...]
    input: Digest
    output: Digest

    @property
    def did_change(self) -> bool:
        return self.input != self.output


class FmtSubsystem(GoalSubsystem):
    name = "fmt"
    help = "Autoformat source code."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return FmtTargetsRequest in union_membership

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


def _batch(
    fmt_subsystem: FmtSubsystem, iterable: Iterable[_T], key: Callable[[_T], str]
) -> Iterator[list[_T]]:
    partitions = partition_sequentially(
        iterable,
        key=key,
        size_target=fmt_subsystem.batch_size,
        size_max=4 * fmt_subsystem.batch_size,
    )
    for partition in partitions:
        yield partition


def _batch_targets(
    fmt_subsystem: FmtSubsystem,
    all_request_types: Iterable[type[FmtTargetsRequest]],
    targets: Iterable[Target],
) -> dict[Targets, tuple[type[FmtTargetsRequest], ...]]:
    """Groups targets by the relevant Request types, then batches them.

    Returns a mapping from batch -> Request types.
    """
    formatters_to_run = determine_specified_tool_names("fmt", fmt_subsystem.only, all_request_types)
    targets_by_request_order = defaultdict(list)

    for target in targets:
        request_types = []
        for request_type in all_request_types:
            valid_name = request_type.name in formatters_to_run
            if valid_name and request_type.field_set_type.is_applicable(target):
                request_types.append(request_type)
        if request_types:
            targets_by_request_order[tuple(request_types)].append(target)

    target_batches_by_fmt_request_order = {
        Targets(target_batch): request_types
        for request_types, targets in targets_by_request_order.items()
        for target_batch in _batch(fmt_subsystem, targets, key=lambda t: t.address.spec)
    }

    return target_batches_by_fmt_request_order


@rule_helper
async def _write_files(workspace: Workspace, batched_results: Iterable[_FmtBatchResult]):
    changed_digests = tuple(
        batched_result.output for batched_result in batched_results if batched_result.did_change
    )
    if changed_digests:
        # NB: this will fail if there are any conflicting changes, which we want to happen rather
        # than silently having one result override the other. In practice, this should never
        # happen due to us grouping each language's formatters into a single digest.
        merged_formatted_digest = await Get(Digest, MergeDigests(changed_digests))
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
        elif all(result.skipped for result in results):
            continue
        else:
            sigil = console.sigil_succeeded()
            status = "made no changes"
        console.print_stderr(f"{sigil} {formatter} {status}.")


@goal_rule
async def fmt(
    console: Console,
    targets: FilteredTargets,
    fmt_subsystem: FmtSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    targets_to_request_types = _batch_targets(
        fmt_subsystem,
        union_membership[FmtTargetsRequest],
        targets,
    )

    target_batch_results = await MultiGet(
        Get(
            _FmtBatchResult,
            _FmtTargetBatchRequest(fmt_request_types, target_batch),
        )
        for target_batch, fmt_request_types in targets_to_request_types.items()
    )

    individual_results = list(
        itertools.chain.from_iterable(result.results for result in target_batch_results)
    )

    if not individual_results:
        return Fmt(exit_code=0)

    await _write_files(workspace, target_batch_results)
    _print_results(console, individual_results)

    # Since the rules to produce FmtResult should use ExecuteRequest, rather than
    # FallibleProcess, we assume that there were no failures.
    return Fmt(exit_code=0)


@rule
async def fmt_target_batch(
    request: _FmtTargetBatchRequest,
) -> _FmtBatchResult:
    original_sources = await Get(
        SourceFiles,
        SourceFilesRequest(target[SourcesField] for target in request.targets),
    )
    prior_snapshot = original_sources.snapshot

    results = []
    for fmt_targets_request_type in request.request_types:
        fmt_targets_request = fmt_targets_request_type(
            (
                fmt_targets_request_type.field_set_type.create(target)
                for target in request.targets
                if fmt_targets_request_type.field_set_type.is_applicable(target)
            ),
            snapshot=prior_snapshot,
        )
        if not fmt_targets_request.field_sets:
            continue
        result = await Get(FmtResult, FmtTargetsRequest, fmt_targets_request)
        results.append(result)
        if not result.skipped:
            prior_snapshot = result.output
    return _FmtBatchResult(
        tuple(results),
        input=original_sources.snapshot.digest,
        output=prior_snapshot.digest,
    )


def rules():
    return collect_rules()
