# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, Iterator, Type, TypeVar, cast

from pants.core.goals.fmt import FmtRequest, FmtResult
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
from pants.engine.fs import EMPTY_DIGEST, Digest, SpecsSnapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import FieldSet, Targets
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import IntOption, StrListOption
from pants.util.collections import partition_sequentially
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.strutil import strip_v2_chroot_path

logger = logging.getLogger(__name__)

_SR = TypeVar("_SR", bound=StyleRequest)


class AmbiguousRequestNamesError(Exception):
    def __init__(
        self,
        ambiguous_name: str,
        requests: set[Type[StyleRequest] | Type[LintFilesRequest]],
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
        "--only",
        help=only_option_help("lint", "linter", "flake8", "shellcheck"),
    )
    batch_size = IntOption(
        "--batch-size",
        advanced=True,
        default=128,
        help=style_batch_size_help(uppercase="Linter", lowercase="linter"),
    )


class Lint(Goal):
    subsystem_cls = LintSubsystem


def _check_ambiguous_request_names(
    *requests: Type[LintFilesRequest] | Type[StyleRequest],
) -> None:
    for name, request_group in itertools.groupby(requests, key=lambda target: target.name):
        request_group_set = set(request_group)

        if len(request_group_set) > 1:
            raise AmbiguousRequestNamesError(name, request_group_set)


@goal_rule
async def lint(
    console: Console,
    workspace: Workspace,
    targets: Targets,
    specs_snapshot: SpecsSnapshot,
    lint_subsystem: LintSubsystem,
    union_membership: UnionMembership,
    dist_dir: DistDir,
) -> Lint:
    lint_target_request_types = cast(
        "Iterable[type[LintTargetsRequest]]", union_membership.get(LintTargetsRequest)
    )
    fmt_target_request_types = cast("Iterable[type[FmtRequest]]", union_membership.get(FmtRequest))
    file_request_types = cast(
        "Iterable[type[LintFilesRequest]]", union_membership[LintFilesRequest]
    )

    _check_ambiguous_request_names(
        *lint_target_request_types, *fmt_target_request_types, *file_request_types
    )

    specified_names = determine_specified_tool_names(
        "lint",
        lint_subsystem.only,
        [
            *lint_target_request_types,
            *fmt_target_request_types,
        ],
        extra_valid_names={request.name for request in file_request_types},
    )

    def is_specified(request_type: type[StyleRequest] | type[LintFilesRequest]):
        return request_type.name in specified_names

    lint_target_request_types = filter(is_specified, lint_target_request_types)
    fmt_target_request_types = filter(is_specified, fmt_target_request_types)
    file_request_types = filter(is_specified, file_request_types)

    def batch(field_sets: Iterable[FieldSet]) -> Iterator[list[FieldSet]]:
        partitions = partition_sequentially(
            field_sets,
            key=lambda fs: fs.address.spec,
            size_target=lint_subsystem.batch_size,
            size_max=4 * lint_subsystem.batch_size,
        )
        for partition in partitions:
            yield partition

    def batch_by_type(
        request_types: Iterable[type[_SR]],
    ) -> tuple[tuple[type[_SR], list[FieldSet]], ...]:
        return tuple(
            (request_type, field_set_batch)
            for request_type in request_types
            for field_set_batch in batch(
                request_type.field_set_type.create(target)
                for target in targets
                if request_type.field_set_type.is_applicable(target)
            )
        )

    lint_target_requests = (
        request_type(batch) for request_type, batch in batch_by_type(lint_target_request_types)
    )

    batched_fmt_request_pairs = batch_by_type(fmt_target_request_types)
    all_fmt_source_batches = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(
                getattr(field_set, "sources", getattr(field_set, "source", None))
                for field_set in batch
            ),
        )
        for _, batch in batched_fmt_request_pairs
    )

    fmt_requests = (
        request_type(
            batch,
            snapshot=source_files_snapshot.snapshot,
        )
        for (request_type, batch), source_files_snapshot in zip(
            batched_fmt_request_pairs, all_fmt_source_batches
        )
    )
    file_requests = (
        tuple(request_type(specs_snapshot.snapshot.files) for request_type in file_request_types)
        if specs_snapshot.snapshot.files
        else ()
    )

    all_requests = [
        *(Get(LintResults, LintTargetsRequest, request) for request in lint_target_requests),
        *(Get(FmtResult, FmtRequest, request) for request in fmt_requests),
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

    def coerce_to_lintresult(batch_results: LintResults | FmtResult) -> tuple[LintResult, ...]:
        if isinstance(batch_results, FmtResult):
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

    exit_code = 0
    if all_results:
        console.print_stderr("")
    for results in all_results:
        if results.skipped:
            continue
        elif results.exit_code == 0:
            sigil = console.sigil_succeeded()
            status = "succeeded"
        else:
            sigil = console.sigil_failed()
            status = "failed"
            exit_code = results.exit_code
        console.print_stderr(f"{sigil} {results.linter_name} {status}.")

    return Lint(exit_code)


def rules():
    return collect_rules()
