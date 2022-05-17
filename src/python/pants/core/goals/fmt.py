# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, TypeVar

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
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import FieldSet, FilteredTargets, SourcesField, Targets
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import IntOption, StrListOption
from pants.util.collections import partition_sequentially
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import strip_v2_chroot_path

_F = TypeVar("_F", bound="FmtResult")
_FS = TypeVar("_FS", bound=FieldSet)

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
        request: FmtRequest,
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
        # changed. We do this for two reasons:
        #   1. This is run as part of both `fmt` and `lint`, and we want consistent output between both
        #   2. Different formatters have different stdout/stderr. This way is consistent across all
        #       formatters.
        if self.did_change:
            output = "".join(
                f"\n  {file}"
                for file in SnapshotDiff.from_snapshots(self.input, self.output).changed_files
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
class FmtRequest(StyleRequest[_FS]):
    snapshot: Snapshot

    def __init__(self, field_sets: Iterable[_FS], snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        super().__init__(field_sets)


@dataclass(frozen=True)
class _LanguageFmtRequest:
    request_types: tuple[type[FmtRequest], ...]
    targets: Targets


@dataclass(frozen=True)
class _LanguageFmtResults:

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
        return FmtRequest in union_membership

    only = StrListOption(
        "--only",
        help=only_option_help("fmt", "formatter", "isort", "shfmt"),
    )
    batch_size = IntOption(
        "--batch-size",
        advanced=True,
        default=128,
        help=style_batch_size_help(uppercase="Formatter", lowercase="formatter"),
    )


class Fmt(Goal):
    subsystem_cls = FmtSubsystem


@goal_rule
async def fmt(
    console: Console,
    targets: FilteredTargets,
    fmt_subsystem: FmtSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    request_types = union_membership[FmtRequest]
    specified_names = determine_specified_tool_names("fmt", fmt_subsystem.only, request_types)

    # Group targets by the sequence of FmtRequests that apply to them.
    targets_by_fmt_request_order = defaultdict(list)
    for target in targets:
        fmt_requests = []
        for fmt_request in request_types:
            valid_name = fmt_request.name in specified_names
            if valid_name and fmt_request.field_set_type.is_applicable(target):  # type: ignore[misc]
                fmt_requests.append(fmt_request)
        if fmt_requests:
            targets_by_fmt_request_order[tuple(fmt_requests)].append(target)

    # Spawn sequential formatting per unique sequence of FmtRequests.
    per_language_results = await MultiGet(
        Get(
            _LanguageFmtResults,
            _LanguageFmtRequest(fmt_requests, Targets(target_batch)),
        )
        for fmt_requests, targets in targets_by_fmt_request_order.items()
        for target_batch in partition_sequentially(
            targets,
            key=lambda t: t.address.spec,
            size_target=fmt_subsystem.batch_size,
            size_max=4 * fmt_subsystem.batch_size,
        )
    )

    individual_results = list(
        itertools.chain.from_iterable(
            language_result.results for language_result in per_language_results
        )
    )

    if not individual_results:
        return Fmt(exit_code=0)

    changed_digests = tuple(
        language_result.output
        for language_result in per_language_results
        if language_result.did_change
    )
    if changed_digests:
        # NB: this will fail if there are any conflicting changes, which we want to happen rather
        # than silently having one result override the other. In practice, this should never
        # happen due to us grouping each language's formatters into a single digest.
        merged_formatted_digest = await Get(Digest, MergeDigests(changed_digests))
        workspace.write_digest(merged_formatted_digest)

    if individual_results:
        console.print_stderr("")

    # We group all results for the same formatter so that we can give one final status in the
    # summary. This is only relevant if there were multiple results because of
    # `--per-file-caching`.
    formatter_to_results = defaultdict(set)
    for result in individual_results:
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

    # Since the rules to produce FmtResult should use ExecuteRequest, rather than
    # FallibleProcess, we assume that there were no failures.
    return Fmt(exit_code=0)


@rule
async def fmt_language(language_fmt_request: _LanguageFmtRequest) -> _LanguageFmtResults:
    original_sources = await Get(
        SourceFiles,
        SourceFilesRequest(target[SourcesField] for target in language_fmt_request.targets),
    )
    prior_formatter_result = original_sources.snapshot

    results = []
    for fmt_request_type in language_fmt_request.request_types:
        request = fmt_request_type(
            (
                fmt_request_type.field_set_type.create(target)
                for target in language_fmt_request.targets
                if fmt_request_type.field_set_type.is_applicable(target)
            ),
            snapshot=prior_formatter_result,
        )
        if not request.field_sets:
            continue
        result = await Get(FmtResult, FmtRequest, request)
        results.append(result)
        if not result.skipped:
            prior_formatter_result = result.output
    return _LanguageFmtResults(
        tuple(results),
        input=original_sources.snapshot.digest,
        output=prior_formatter_result.digest,
    )


def rules():
    return collect_rules()
