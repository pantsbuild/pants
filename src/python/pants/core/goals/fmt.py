# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
import os
from abc import ABCMeta
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, ClassVar, Iterable, Iterator, TypeVar, cast

from pants.base.specs import Specs
from pants.core.goals.style_request import (
    StyleRequest,
    determine_specified_tool_names,
    only_option_help,
    style_batch_size_help,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import (
    Digest,
    MergeDigests,
    PathGlobs,
    Snapshot,
    SnapshotDiff,
    SpecsPaths,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.native_engine import EMPTY_SNAPSHOT
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule, rule_helper
from pants.engine.target import FieldSet, FilteredTargets, SourcesField, Target, Targets
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import IntOption, StrListOption
from pants.source.filespec import FilespecMatcher
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
        request: FmtTargetsRequest | _FmtBuildFilesRequest,
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


@union
@dataclass(frozen=True)
# Prefixed with `_` because we aren't sure if this union will stick long-term, or be subsumed when
# we implement https://github.com/pantsbuild/pants/issues/16480.
class _FmtBuildFilesRequest(EngineAwareParameter, metaclass=ABCMeta):
    name: ClassVar[str]

    snapshot: Snapshot


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
class _FmtBuildFilesBatchRequest:
    request_types: tuple[type[_FmtBuildFilesRequest], ...]
    paths: tuple[str, ...]


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


def _get_request_types(
    fmt_subsystem: FmtSubsystem,
    union_membership: UnionMembership,
) -> tuple[tuple[type[FmtTargetsRequest], ...], tuple[type[_FmtBuildFilesRequest], ...]]:
    fmt_target_request_types = union_membership.get(FmtTargetsRequest)
    fmt_build_files_request_types = union_membership.get(_FmtBuildFilesRequest)

    # NOTE: Unlike lint.py, we don't check for ambiguous names between target formatters and BUILD
    # formatters, since BUILD files are Python and we re-use Python formatters for BUILD files
    # (like `black`).

    formatters_to_run = determine_specified_tool_names(
        "fmt",
        fmt_subsystem.only,
        fmt_target_request_types,
        extra_valid_names=(fbfrt.name for fbfrt in fmt_build_files_request_types),
    )

    filtered_fmt_target_request_types = tuple(
        request_type
        for request_type in fmt_target_request_types
        if request_type.name in formatters_to_run
    )
    filtered_fmt_build_files_request_types = tuple(
        request_type
        for request_type in fmt_build_files_request_types
        if request_type.name in formatters_to_run
    )

    return filtered_fmt_target_request_types, filtered_fmt_build_files_request_types


def _batch(
    iterable: Iterable[_T], batch_size: int, key: Callable[[_T], str] = lambda x: str(x)
) -> Iterator[list[_T]]:
    partitions = partition_sequentially(
        iterable,
        key=key,
        size_target=batch_size,
        size_max=4 * batch_size,
    )
    for partition in partitions:
        yield partition


def _batch_targets(
    request_types: Iterable[type[FmtTargetsRequest]],
    targets: Iterable[Target],
    batch_size: int,
) -> dict[Targets, tuple[type[FmtTargetsRequest], ...]]:
    """Groups targets by the relevant Request types, then batches them.

    Returns a mapping from batch -> Request types.
    """

    targets_by_request_order = defaultdict(list)

    for target in targets:
        applicable_request_types = []
        for request_type in request_types:
            if request_type.field_set_type.is_applicable(target):
                applicable_request_types.append(request_type)
        if applicable_request_types:
            targets_by_request_order[tuple(applicable_request_types)].append(target)

    target_batches_by_fmt_request_order = {
        Targets(target_batch): applicable_request_types
        for applicable_request_types, targets in targets_by_request_order.items()
        for target_batch in _batch(targets, batch_size, key=lambda t: t.address.spec)
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
    specs: Specs,
    fmt_subsystem: FmtSubsystem,
    build_file_options: BuildFileOptions,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    fmt_target_request_types, fmt_build_files_request_types = _get_request_types(
        fmt_subsystem, union_membership
    )

    _get_targets = Get(
        FilteredTargets,
        Specs,
        specs if fmt_target_request_types else Specs.empty(),
    )
    _get_specs_paths = Get(
        SpecsPaths, Specs, specs if fmt_build_files_request_types else Specs.empty()
    )

    targets, specs_paths = await MultiGet(_get_targets, _get_specs_paths)
    specified_build_files = FilespecMatcher(
        includes=[os.path.join("**", p) for p in build_file_options.patterns],
        excludes=build_file_options.ignores,
    ).matches(specs_paths.files)

    targets_to_request_types = _batch_targets(
        fmt_target_request_types,
        targets,
        fmt_subsystem.batch_size,
    )

    all_requests = [
        *(
            Get(
                _FmtBatchResult,
                _FmtTargetBatchRequest(fmt_request_types, target_batch),
            )
            for target_batch, fmt_request_types in targets_to_request_types.items()
        ),
        *(
            Get(
                _FmtBatchResult,
                _FmtBuildFilesBatchRequest(fmt_build_files_request_types, tuple(paths_batch)),
            )
            for paths_batch in _batch(
                specified_build_files,
                fmt_subsystem.batch_size,
            )
        ),
    ]
    target_batch_results = cast(
        "tuple[_FmtBatchResult, ...]", await MultiGet(all_requests)  # type: ignore[arg-type]
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
async def fmt_build_files(
    request: _FmtBuildFilesBatchRequest,
) -> _FmtBatchResult:
    original_snapshot = await Get(Snapshot, PathGlobs(request.paths))
    prior_snapshot = original_snapshot

    results = []
    for fmt_build_files_request_type in request.request_types:
        fmt_build_files_request = fmt_build_files_request_type(
            snapshot=prior_snapshot,
        )
        result = await Get(FmtResult, _FmtBuildFilesRequest, fmt_build_files_request)
        results.append(result)
        prior_snapshot = result.output
    return _FmtBatchResult(
        tuple(results),
        input=original_snapshot.digest,
        output=prior_snapshot.digest,
    )


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
