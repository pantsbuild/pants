# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, cast

from pants.core.goals.style_request import (
    StyleRequest,
    determine_specified_tool_names,
    only_option_help,
    style_batch_size_help,
    write_reports,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, Digest, SpecsSnapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import FieldSet, Targets
from pants.engine.unions import UnionMembership, union
from pants.util.collections import partition_sequentially
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.strutil import strip_v2_chroot_path

logger = logging.getLogger(__name__)


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
    """AThe entry point for linters that need targets."""


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

    required_union_implementations = (LintTargetsRequest,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--only",
            type=list,
            member_type=str,
            default=[],
            help=only_option_help("lint", "linter", "flake8", "shellcheck"),
        )
        register(
            "--per-file-caching",
            advanced=True,
            type=bool,
            default=False,
            removal_version="2.11.0.dev0",
            removal_hint=(
                "Linters are now broken into multiple batches by default using the "
                "`--batch-size` argument.\n"
                "\n"
                "To keep (roughly) this option's behavior, set [lint].batch_size = 1. However, "
                "you'll likely get better performance by using a larger batch size because of "
                "reduced overhead launching processes."
            ),
            help=(
                "Rather than linting all files in a single batch, lint each file as a "
                "separate process.\n\nWhy do this? You'll get many more cache hits. Why not do "
                "this? Linters both have substantial startup overhead and are cheap to add one "
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
            help=style_batch_size_help(uppercase="Linter", lowercase="linter"),
        )

    @property
    def only(self) -> tuple[str, ...]:
        return tuple(self.options.only)

    @property
    def per_file_caching(self) -> bool:
        return cast(bool, self.options.per_file_caching)

    @property
    def batch_size(self) -> int:
        return cast(int, self.options.batch_size)


class Lint(Goal):
    subsystem_cls = LintSubsystem


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
    target_request_types = cast(
        "Iterable[type[LintTargetsRequest]]", union_membership[LintTargetsRequest]
    )
    file_request_types = union_membership[LintFilesRequest]
    specified_names = determine_specified_tool_names(
        "lint",
        lint_subsystem.only,
        target_request_types,
        extra_valid_names={request.name for request in file_request_types},
    )
    target_requests = tuple(
        request_type(
            request_type.field_set_type.create(target)
            for target in targets
            if (
                request_type.name in specified_names
                and request_type.field_set_type.is_applicable(target)
            )
        )
        for request_type in target_request_types
    )
    file_requests = (
        tuple(
            request_type(specs_snapshot.snapshot.files)
            for request_type in file_request_types
            if request_type.name in specified_names
        )
        if specs_snapshot.snapshot.files
        else ()
    )

    if lint_subsystem.per_file_caching:
        all_requests = [
            *(
                Get(LintResults, LintTargetsRequest, request.__class__([field_set]))
                for request in target_requests
                if request.field_sets
                for field_set in request.field_sets
            ),
            *(
                Get(LintResults, LintFilesRequest, request.__class__((fp,)))
                for request in file_requests
                for fp in request.file_paths
            ),
        ]
    else:

        def address_str(fs: FieldSet) -> str:
            return fs.address.spec

        all_requests = [
            *(
                Get(LintResults, LintTargetsRequest, request.__class__(field_set_batch))
                for request in target_requests
                if request.field_sets
                for field_set_batch in partition_sequentially(
                    request.field_sets,
                    key=address_str,
                    size_target=lint_subsystem.batch_size,
                    size_max=4 * lint_subsystem.batch_size,
                )
            ),
            *(Get(LintResults, LintFilesRequest, request) for request in file_requests),
        ]

    all_batch_results = cast(
        "tuple[LintResults, ...]",
        await MultiGet(all_requests),  # type: ignore[arg-type]
    )

    def key_fn(results: LintResults):
        return results.linter_name

    # NB: We must pre-sort the data for itertools.groupby() to work properly.
    sorted_all_batch_results = sorted(all_batch_results, key=key_fn)
    # We consolidate all results for each linter into a single `LintResults`.
    all_results = tuple(
        sorted(
            (
                LintResults(
                    itertools.chain.from_iterable(
                        per_file_results.results for per_file_results in all_linter_results
                    ),
                    linter_name=linter_name,
                )
                for linter_name, all_linter_results in itertools.groupby(
                    sorted_all_batch_results, key=key_fn
                )
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
