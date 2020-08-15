# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional, cast

from pants.core.goals.style_request import StyleRequest
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.fs import Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.util.strutil import strip_v2_chroot_path

logger = logging.Logger(__name__)


@dataclass(frozen=True)
class LintReport:
    file_name: str
    digest: Digest


class InvalidLinterReportsError(Exception):
    pass


@dataclass(frozen=True)
class LintResult:
    exit_code: int
    stdout: str
    stderr: str
    linter_name: str
    report: Optional[LintReport]

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult,
        *,
        linter_name: str,
        strip_chroot_path: bool = False,
        report: Optional[LintReport] = None,
    ) -> "LintResult":
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return LintResult(
            exit_code=process_result.exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            linter_name=linter_name,
            report=report,
        )


class LintResults(Collection[LintResult]):
    """Zero or more LintResult objects for a single linter.

    Typically, linters will return one result. If they no-oped, they will return zero results.
    However, some linters may need to partition their input and thus may need to return multiple
    results. For example, many Python linters will need to group by interpreter compatibility.
    """


@union
class LintRequest(StyleRequest):
    """A union for StyleRequests that should be lintable.

    Subclass and install a member of this type to provide a linter.
    """


class LintSubsystem(GoalSubsystem):
    """Lint source code."""

    name = "lint"

    required_union_implementations = (LintRequest,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--per-target-caching",
            advanced=True,
            type=bool,
            default=False,
            help=(
                "Rather than running all targets in a single batch, run each target as a "
                "separate process. Why do this? You'll get many more cache hits. Why not do this? "
                "Linters both have substantial startup overhead and are cheap to add one "
                "additional file to the run. On a cold cache, it is much faster to use "
                "`--no-per-target-caching`. We only recommend using `--per-target-caching` if you "
                "are using a remote cache or if you have benchmarked that this option will be "
                "faster than `--no-per-target-caching` for your use case."
            ),
        )
        register(
            "--reports-dir",
            type=str,
            metavar="<DIR>",
            default=None,
            advanced=True,
            help=(
                "Specifying a directory causes linters that support writing report files to write "
                "into this directory.",
            ),
        )

    @property
    def per_target_caching(self) -> bool:
        return cast(bool, self.options.per_target_caching)

    @property
    def reports_dir(self) -> Optional[str]:
        return cast(Optional[str], self.options.reports_dir)


class Lint(Goal):
    subsystem_cls = LintSubsystem


@goal_rule
async def lint(
    console: Console,
    workspace: Workspace,
    targets: Targets,
    lint_subsystem: LintSubsystem,
    union_membership: UnionMembership,
) -> Lint:
    request_types = union_membership[LintRequest]
    requests: Iterable[StyleRequest] = tuple(
        request_type(
            request_type.field_set_type.create(target)
            for target in targets
            if request_type.field_set_type.is_valid(target)
        )
        for request_type in request_types
    )
    field_sets_with_sources: Iterable[FieldSetsWithSources] = await MultiGet(
        Get(FieldSetsWithSources, FieldSetsWithSourcesRequest(request.field_sets))
        for request in requests
    )
    valid_requests: Iterable[StyleRequest] = tuple(
        request_cls(request)
        for request_cls, request in zip(request_types, field_sets_with_sources)
        if request
    )

    if lint_subsystem.per_target_caching:
        results = await MultiGet(
            Get(LintResults, LintRequest, request.__class__([field_set]))
            for request in valid_requests
            for field_set in request.field_sets
        )
    else:
        results = await MultiGet(
            Get(LintResults, LintRequest, lint_request) for lint_request in valid_requests
        )

    sorted_results = sorted(itertools.chain.from_iterable(results), key=lambda res: res.linter_name)
    if not sorted_results:
        return Lint(exit_code=0)

    linter_to_reports = defaultdict(list)
    for result in sorted_results:
        if result.report:
            linter_to_reports[result.linter_name].append(result.report)
    if linter_to_reports:
        # TODO(#10532): Tolerate when a linter has multiple reports.
        linters_with_multiple_reports = [
            linter for linter, reports in linter_to_reports.items() if len(reports) > 1
        ]
        if linters_with_multiple_reports:
            if lint_subsystem.per_target_caching:
                suggestion = "Try running without `--lint-per-target-caching` set."
            else:
                suggestion = (
                    "The linters likely partitioned the input targets, such as grouping by Python "
                    "interpreter compatibility. Try running on fewer targets or unset "
                    "`--lint-reports-dir`."
                )
            raise InvalidLinterReportsError(
                "Multiple reports would have been written for these linters: "
                f"{linters_with_multiple_reports}. The option `--lint-reports-dir` only works if "
                f"each linter has a single result. {suggestion}"
            )
        reports = itertools.chain.from_iterable(linter_to_reports.values())
        merged_reports = await Get(Digest, MergeDigests(report.digest for report in reports))
        workspace.write_digest(merged_reports, path_prefix=lint_subsystem.reports_dir)
        logger.info(f"Wrote lint result files to {lint_subsystem.reports_dir}.")

    exit_code = 0
    for result in sorted_results:
        if result.exit_code == 0:
            sigil = console.green("✓")
            status = "succeeded"
        else:
            sigil = console.red("𐄂")
            status = "failed"
            exit_code = result.exit_code
        console.print_stderr(f"{sigil} {result.linter_name} {status}.")
        if result.stdout:
            console.print_stderr(result.stdout)
        if result.stderr:
            console.print_stderr(result.stderr)
        if result != sorted_results[-1]:
            console.print_stderr("")

    return Lint(exit_code)


def rules():
    return collect_rules()
