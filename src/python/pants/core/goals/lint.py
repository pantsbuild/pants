# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Iterable, Iterator, TypeVar, cast

from pants.base.specs import Specs
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, _FmtBuildFilesRequest
from pants.core.goals.style_request import (
    StyleRequest,
    determine_specified_tool_names,
    only_option_help,
    style_batch_size_help,
    write_reports,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, Digest, PathGlobs, Snapshot, SpecsPaths, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.native_engine import FilespecMatcher
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import FieldSet, FilteredTargets, SourcesField
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import BoolOption, IntOption, StrListOption
from pants.util.collections import partition_sequentially
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.strutil import softwrap, strip_v2_chroot_path

logger = logging.getLogger(__name__)

_SR = TypeVar("_SR", bound=StyleRequest)
_T = TypeVar("_T")


class AmbiguousRequestNamesError(Exception):
    def __init__(
        self,
        ambiguous_name: str,
        requests: set[type],
    ):
        request_names = {
            f"{request_target.__module__}.{request_target.__qualname__}"
            for request_target in requests
        }

        super().__init__(
            f"The same name `{ambiguous_name}` is used by multiple requests, "
            f"which causes ambiguity: {request_names}\n\n"
            f"To fix, please update these requests so that `{ambiguous_name}` "
            f"is not used more than once."
        )


@dataclass(frozen=True)
class LintResult(EngineAwareReturnType):
    exit_code: int
    stdout: str
    stderr: str
    partition_description: str | None = None
    report: Digest = EMPTY_DIGEST

    @classmethod
    def from_fallible_process_result(
        cls,
        process_result: FallibleProcessResult,
        *,
        partition_description: str | None = None,
        strip_chroot_path: bool = False,
        report: Digest = EMPTY_DIGEST,
    ) -> LintResult:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return cls(
            exit_code=process_result.exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            partition_description=partition_description,
            report=report,
        )

    def metadata(self) -> dict[str, Any]:
        return {"partition": self.partition_description}


@frozen_after_init
@dataclass(unsafe_hash=True)
class LintResults(EngineAwareReturnType):
    """Zero or more LintResult objects for a single linter.

    Typically, linters will return one result. If they no-oped, they will return zero results.
    However, some linters may need to partition their input and thus may need to return multiple
    results. For example, many Python linters will need to group by interpreter compatibility.
    """

    results: tuple[LintResult, ...]
    linter_name: str

    def __init__(self, results: Iterable[LintResult], *, linter_name: str) -> None:
        self.results = tuple(results)
        self.linter_name = linter_name

    @property
    def skipped(self) -> bool:
        return bool(self.results) is False

    @memoized_property
    def exit_code(self) -> int:
        return next((result.exit_code for result in self.results if result.exit_code != 0), 0)

    def level(self) -> LogLevel | None:
        if self.skipped:
            return LogLevel.DEBUG
        return LogLevel.ERROR if self.exit_code != 0 else LogLevel.INFO

    def message(self) -> str | None:
        if self.skipped:
            return f"{self.linter_name} skipped."
        message = self.linter_name
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )

        def msg_for_result(result: LintResult) -> str:
            msg = ""
            if result.stdout:
                msg += f"\n{result.stdout}"
            if result.stderr:
                msg += f"\n{result.stderr}"
            if msg:
                msg = f"{msg.rstrip()}\n\n"
            return msg

        if len(self.results) == 1:
            results_msg = msg_for_result(self.results[0])
        else:
            results_msg = "\n"
            for i, result in enumerate(self.results):
                msg = f"Partition #{i + 1}"
                msg += (
                    f" - {result.partition_description}:" if result.partition_description else ":"
                )
                msg += msg_for_result(result) or "\n\n"
                results_msg += msg
        message += results_msg
        return message

    def cacheable(self) -> bool:
        """Is marked uncacheable to ensure that it always renders."""
        return False


@union
class LintTargetsRequest(StyleRequest):
    """The entry point for linters that need targets."""


@union
@dataclass(frozen=True)
class LintFilesRequest(EngineAwareParameter):
    """The entry point for linters that do not use targets."""

    name: ClassVar[str]

    file_paths: tuple[str, ...]

    def debug_hint(self) -> str:
        return self.name


# If a user wants linter reports to show up in dist/ they must ensure that the reports
# are written under this directory. E.g.,
# ./pants --flake8-args="--output-file=reports/report.txt" lint <target>
REPORT_DIR = "reports"


class LintSubsystem(GoalSubsystem):
    name = "lint"
    help = "Run all linters and/or formatters in check mode."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return LintTargetsRequest in union_membership or LintFilesRequest in union_membership

    only = StrListOption(
        help=only_option_help("lint", "linter", "flake8", "shellcheck"),
    )
    skip_formatters = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, skip running all formatters in check-only mode.

            FYI: when running `{bin_name()} fmt lint ::`, there should be little performance
            benefit to using this flag. Pants will reuse the results from `fmt` when running `lint`.
            """
        ),
    )
    batch_size = IntOption(
        advanced=True,
        default=128,
        help=style_batch_size_help(uppercase="Linter", lowercase="linter"),
    )


class Lint(Goal):
    subsystem_cls = LintSubsystem


def _check_ambiguous_request_names(
    *requests: type,
) -> None:
    def key(target: type) -> str:
        return target.name  # type: ignore[attr-defined,no-any-return]

    for name, request_group in itertools.groupby(requests, key=key):
        request_group_set = set(request_group)

        if len(request_group_set) > 1:
            raise AmbiguousRequestNamesError(name, request_group_set)


def _print_results(
    console: Console,
    results: tuple[LintResults, ...],
    formatter_failed: bool,
) -> None:
    if results:
        console.print_stderr("")

    for result in results:
        if result.skipped:
            continue
        elif result.exit_code == 0:
            sigil = console.sigil_succeeded()
            status = "succeeded"
        else:
            sigil = console.sigil_failed()
            status = "failed"
        console.print_stderr(f"{sigil} {result.linter_name} {status}.")

    if formatter_failed:
        console.print_stderr("")
        console.print_stderr(f"(One or more formatters failed. Run `{bin_name()} fmt` to fix.)")


def _get_error_code(results: tuple[LintResults, ...]) -> int:
    for result in reversed(results):
        if result.exit_code:
            return result.exit_code
    return 0


@goal_rule
async def lint(
    console: Console,
    workspace: Workspace,
    specs: Specs,
    build_file_options: BuildFileOptions,
    lint_subsystem: LintSubsystem,
    union_membership: UnionMembership,
    dist_dir: DistDir,
) -> Lint:
    lint_target_request_types = cast(
        "Iterable[type[LintTargetsRequest]]", union_membership.get(LintTargetsRequest)
    )
    fmt_target_request_types = cast(
        "Iterable[type[FmtTargetsRequest]]", union_membership.get(FmtTargetsRequest)
    )
    fmt_build_request_types = cast(
        "Iterable[type[_FmtBuildFilesRequest]]", union_membership.get(_FmtBuildFilesRequest)
    )
    file_request_types = cast(
        "Iterable[type[LintFilesRequest]]", union_membership[LintFilesRequest]
    )

    # NB: Target formatters and build file formatters can share a name, so we can't check them both
    # for ambiguity at the same time.
    _check_ambiguous_request_names(
        *lint_target_request_types,
        *fmt_target_request_types,
        *file_request_types,
    )

    _check_ambiguous_request_names(
        *lint_target_request_types,
        *fmt_build_request_types,
        *file_request_types,
    )

    specified_names = determine_specified_tool_names(
        "lint",
        lint_subsystem.only,
        [*lint_target_request_types, *fmt_target_request_types],
        extra_valid_names={
            request.name  # type: ignore[attr-defined]
            for request in [*file_request_types, *fmt_build_request_types]
        },
    )

    def is_specified(request_type: type):
        return request_type.name in specified_names  # type: ignore[attr-defined]

    lint_target_request_types = filter(is_specified, lint_target_request_types)
    fmt_target_request_types = filter(is_specified, fmt_target_request_types)
    fmt_build_request_types = filter(is_specified, fmt_build_request_types)
    file_request_types = filter(is_specified, file_request_types)

    _get_targets = Get(
        FilteredTargets,
        Specs,
        specs if lint_target_request_types or fmt_target_request_types else Specs.empty(),
    )
    _get_specs_paths = Get(
        SpecsPaths, Specs, specs if file_request_types or fmt_build_request_types else Specs.empty()
    )
    targets, specs_paths = await MultiGet(_get_targets, _get_specs_paths)

    specified_build_files = FilespecMatcher(
        includes=[os.path.join("**", p) for p in build_file_options.patterns],
        excludes=build_file_options.ignores,
    ).matches(specs_paths.files)

    def batch(
        iterable: Iterable[_T], key: Callable[[_T], str] = lambda x: str(x)
    ) -> Iterator[list[_T]]:
        partitions = partition_sequentially(
            iterable,
            key=key,
            size_target=lint_subsystem.batch_size,
            size_max=4 * lint_subsystem.batch_size,
        )
        for partition in partitions:
            yield partition

    def batch_by_type(
        request_types: Iterable[type[_SR]],
    ) -> tuple[tuple[type[_SR], list[FieldSet]], ...]:
        def key(fs: FieldSet) -> str:
            return fs.address.spec

        return tuple(
            (request_type, field_set_batch)
            for request_type in request_types
            for field_set_batch in batch(
                (
                    request_type.field_set_type.create(target)
                    for target in targets
                    if request_type.field_set_type.is_applicable(target)
                ),
                key=key,
            )
        )

    lint_target_requests = (
        request_type(batch) for request_type, batch in batch_by_type(lint_target_request_types)
    )

    fmt_target_requests: Iterable[FmtTargetsRequest] = ()
    fmt_build_requests: Iterable[_FmtBuildFilesRequest] = ()
    if not lint_subsystem.skip_formatters:
        batched_fmt_target_request_pairs = batch_by_type(fmt_target_request_types)
        all_fmt_source_batches = await MultiGet(
            Get(
                SourceFiles,
                SourceFilesRequest(
                    cast(
                        SourcesField,
                        getattr(field_set, "sources", getattr(field_set, "source", None)),
                    )
                    for field_set in batch
                ),
            )
            for _, batch in batched_fmt_target_request_pairs
        )
        fmt_target_requests = (
            request_type(
                batch,
                snapshot=source_files_snapshot.snapshot,
            )
            for (request_type, batch), source_files_snapshot in zip(
                batched_fmt_target_request_pairs, all_fmt_source_batches
            )
        )

        build_file_batch_snapshots = await MultiGet(
            Get(Snapshot, PathGlobs(paths_batch)) for paths_batch in batch(specified_build_files)
        )
        fmt_build_requests = (
            fmt_build_request_type(snapshot)
            for fmt_build_request_type in fmt_build_request_types
            for snapshot in build_file_batch_snapshots
        )

    file_requests = (
        tuple(request_type(specs_paths.files) for request_type in file_request_types)
        if specs_paths.files
        else ()
    )

    all_requests = [
        *(Get(LintResults, LintTargetsRequest, request) for request in lint_target_requests),
        *(Get(FmtResult, FmtTargetsRequest, request) for request in fmt_target_requests),
        *(Get(FmtResult, _FmtBuildFilesRequest, request) for request in fmt_build_requests),
        *(Get(LintResults, LintFilesRequest, request) for request in file_requests),
    ]
    all_batch_results = cast(
        "tuple[LintResults | FmtResult, ...]",
        await MultiGet(all_requests),  # type: ignore[arg-type]
    )

    def key_fn(results: LintResults | FmtResult):
        if isinstance(results, FmtResult):
            return results.formatter_name
        return results.linter_name

    # NB: We must pre-sort the data for itertools.groupby() to work properly.
    sorted_all_batch_results = sorted(all_batch_results, key=key_fn)

    formatter_failed = False

    def coerce_to_lintresult(batch_results: LintResults | FmtResult) -> tuple[LintResult, ...]:
        if isinstance(batch_results, FmtResult):
            nonlocal formatter_failed
            formatter_failed = formatter_failed or batch_results.did_change
            return (
                LintResult(
                    1 if batch_results.did_change else 0,
                    batch_results.stdout,
                    batch_results.stderr,
                ),
            )
        return batch_results.results

    # We consolidate all results for each linter into a single `LintResults`.
    all_results = tuple(
        sorted(
            (
                LintResults(
                    itertools.chain.from_iterable(
                        coerce_to_lintresult(batch_results) for batch_results in results
                    ),
                    linter_name=linter_name,
                )
                for linter_name, results in itertools.groupby(sorted_all_batch_results, key=key_fn)
            ),
            key=key_fn,
        )
    )

    def get_name(res: LintResults) -> str:
        return res.linter_name

    write_reports(
        all_results,
        workspace,
        dist_dir,
        goal_name=LintSubsystem.name,
        get_name=get_name,
    )

    _print_results(
        console,
        all_results,
        formatter_failed,
    )
    return Lint(_get_error_code(all_results))


def rules():
    return collect_rules()
