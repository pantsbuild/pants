# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass
from typing import TypeVar, cast

from pants.core.goals.style_request import StyleRequest, style_batch_size_help
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import SourcesField, Targets
from pants.engine.unions import UnionMembership, union
from pants.util.collections import partition_sequentially
from pants.util.logging import LogLevel
from pants.util.strutil import strip_v2_chroot_path

_F = TypeVar("_F", bound="FmtResult")


@dataclass(frozen=True)
class FmtResult(EngineAwareReturnType):
    input: Digest
    output: Digest
    stdout: str
    stderr: str
    formatter_name: str

    @classmethod
    def skip(cls: type[_F], *, formatter_name: str) -> _F:
        return cls(
            input=EMPTY_DIGEST,
            output=EMPTY_DIGEST,
            stdout="",
            stderr="",
            formatter_name=formatter_name,
        )

    @classmethod
    def from_process_result(
        cls,
        process_result: ProcessResult | FallibleProcessResult,
        *,
        original_digest: Digest,
        formatter_name: str,
        strip_chroot_path: bool = False,
    ) -> FmtResult:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return cls(
            input=original_digest,
            output=process_result.output_digest,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            formatter_name=formatter_name,
        )

    @property
    def skipped(self) -> bool:
        return (
            self.input == EMPTY_DIGEST
            and self.output == EMPTY_DIGEST
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
        output = ""
        if self.stdout:
            output += f"\n{self.stdout}"
        if self.stderr:
            output += f"\n{self.stderr}"
        if output:
            output = f"{output.rstrip()}\n\n"
        return f"{self.formatter_name} {message}{output}"

    def cacheable(self) -> bool:
        """Is marked uncacheable to ensure that it always renders."""
        return False


@union
class FmtRequest(StyleRequest):
    pass


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

    required_union_implementations = (FmtRequest,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--per-file-caching",
            advanced=True,
            type=bool,
            default=False,
            removal_version="2.11.0.dev0",
            removal_hint=(
                "Formatters are now broken into multiple batches by default using the "
                "`--batch-size` argument.\n"
                "\n"
                "To keep (roughly) this option's behavior, set [fmt].batch_size = 1. However, "
                "you'll likely get better performance by using a larger batch size because of "
                "reduced overhead launching processes."
            ),
            help=(
                "Rather than formatting all files in a single batch, format each file as a "
                "separate process.\n\nWhy do this? You'll get many more cache hits. Why not do "
                "this? Formatters both have substantial startup overhead and are cheap to add one "
                "additional file to the run. On a cold cache, it is much faster to use "
                "`--no-per-file-caching`.\n\nWe only recommend using `--per-file-caching` if you "
                "are using a remote cache or if you have benchmarked that this option will be "
                "faster than `--no-per-file-caching` for your use case."
            ),
        )
        register(
            "--batch-size",
            advanced=True,
            type=int,
            default=128,
            help=style_batch_size_help(uppercase="Formatter", lowercase="formatter"),
        )

    @property
    def per_file_caching(self) -> bool:
        return cast(bool, self.options.per_file_caching)

    @property
    def batch_size(self) -> int:
        return cast(int, self.options.batch_size)


class Fmt(Goal):
    subsystem_cls = FmtSubsystem


@goal_rule
async def fmt(
    console: Console,
    targets: Targets,
    fmt_subsystem: FmtSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    # Group targets by the sequence of FmtRequests that apply to them.
    targets_by_fmt_request_order = defaultdict(list)
    for target in targets:
        fmt_requests = []
        for fmt_request in union_membership[FmtRequest]:
            if fmt_request.field_set_type.is_applicable(target):  # type: ignore[misc]
                fmt_requests.append(fmt_request)
        if fmt_requests:
            targets_by_fmt_request_order[tuple(fmt_requests)].append(target)

    # Spawn sequential formatting per unique sequence of FmtRequests.
    if fmt_subsystem.per_file_caching:
        per_language_results = await MultiGet(
            Get(
                _LanguageFmtResults,
                _LanguageFmtRequest(fmt_requests, Targets([target])),
            )
            for fmt_requests, targets in targets_by_fmt_request_order.items()
            for target in targets
        )
    else:
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
            sigil = console.sigil_skipped()
            status = "skipped"
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
            prior_formatter_result=prior_formatter_result,
        )
        if not request.field_sets:
            continue
        result = await Get(FmtResult, FmtRequest, request)
        results.append(result)
        if result.did_change:
            prior_formatter_result = await Get(Snapshot, Digest, result.output)
    return _LanguageFmtResults(
        tuple(results),
        input=original_sources.snapshot.digest,
        output=prior_formatter_result.digest,
    )


def rules():
    return collect_rules()
