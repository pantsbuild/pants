# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple, cast

from pants.core.goals.style_request import StyleRequest, write_reports
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, Digest, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, _uncacheable_rule, collect_rules, goal_rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.strutil import strip_v2_chroot_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LintReport:
    digest: Digest


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
        partition_description: Optional[str] = None,
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

    def metadata(self) -> Dict[str, Any]:
        return {"partition": self.partition_description}


@frozen_after_init
@dataclass(unsafe_hash=True)
class LintResults:
    """Zero or more LintResult objects for a single linter.

    Typically, linters will return one result. If they no-oped, they will return zero results.
    However, some linters may need to partition their input and thus may need to return multiple
    results. For example, many Python linters will need to group by interpreter compatibility.
    """

    results: Tuple[LintResult, ...]
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


class EnrichedLintResults(LintResults, EngineAwareReturnType):
    """`LintResults` that are enriched for the sake of logging results as they come in.

    Plugin authors only need to return `LintResults`, and a rule will upcast those into
    `EnrichedLintResults`.
    """

    def level(self) -> Optional[LogLevel]:
        if self.skipped:
            return LogLevel.DEBUG
        return LogLevel.WARN if self.exit_code != 0 else LogLevel.INFO

    def message(self) -> Optional[str]:
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


@union
class LintRequest(StyleRequest):
    """A union for StyleRequests that should be lintable.

    Subclass and install a member of this type to provide a linter.
    """


# If a user wants linter reports to show up in dist/ they must ensure that the reports
# are written under this directory. E.g.,
# ./pants --flake8-args="--output-file=reports/report.txt" lint <target>
REPORT_DIR = "reports"


class LintSubsystem(GoalSubsystem):
    name = "lint"
    help = "Run all linters and/or formatters in check mode."

    required_union_implementations = (LintRequest,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--per-file-caching",
            advanced=True,
            type=bool,
            default=False,
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
            "--reports-dir",
            type=str,
            metavar="<DIR>",
            default=None,
            advanced=True,
            help=(
                "Specifying a directory causes linters that support writing report files to write "
                "into this directory."
            ),
            removal_version="2.7.0.dev0",
            removal_hint=f"Edit the config file for the linter in question, or set its args via "
            f"Pants options, to cause it to write reports under f{REPORT_DIR} .",
        )

    @property
    def per_file_caching(self) -> bool:
        return cast(bool, self.options.per_file_caching)


class Lint(Goal):
    subsystem_cls = LintSubsystem


@goal_rule
async def lint(
    console: Console,
    workspace: Workspace,
    targets: Targets,
    lint_subsystem: LintSubsystem,
    union_membership: UnionMembership,
    dist_dir: DistDir,
) -> Lint:
    request_types = cast("Iterable[type[StyleRequest]]", union_membership[LintRequest])
    requests = tuple(
        request_type(
            request_type.field_set_type.create(target)
            for target in targets
            if request_type.field_set_type.is_applicable(target)
        )
        for request_type in request_types
    )
    field_sets_with_sources = await MultiGet(
        Get(FieldSetsWithSources, FieldSetsWithSourcesRequest(request.field_sets))
        for request in requests
    )
    valid_requests = tuple(
        request_cls(request)
        for request_cls, request in zip(request_types, field_sets_with_sources)
        if request
    )

    if lint_subsystem.per_file_caching:
        all_per_file_results = await MultiGet(
            Get(EnrichedLintResults, LintRequest, request.__class__([field_set]))
            for request in valid_requests
            for field_set in request.field_sets
        )

        def key_fn(results: EnrichedLintResults):
            return results.linter_name

        # NB: We must pre-sort the data for itertools.groupby() to work properly.
        sorted_all_per_files_results = sorted(all_per_file_results, key=key_fn)
        # We consolidate all results for each linter into a single `LintResults`.
        all_results = tuple(
            EnrichedLintResults(
                itertools.chain.from_iterable(
                    per_file_results.results for per_file_results in all_linter_results
                ),
                linter_name=linter_name,
            )
            for linter_name, all_linter_results in itertools.groupby(
                sorted_all_per_files_results, key=key_fn
            )
        )
    else:
        all_results = await MultiGet(
            Get(EnrichedLintResults, LintRequest, lint_request) for lint_request in valid_requests
        )

    all_results = tuple(sorted(all_results, key=lambda results: results.linter_name))

    def get_tool_name(res: LintResults) -> str:
        return res.linter_name

    write_reports(
        all_results,
        workspace,
        dist_dir,
        goal_name=LintSubsystem.name,
        get_tool_name=get_tool_name,
    )

    exit_code = 0
    if all_results:
        console.print_stderr("")
    for results in all_results:
        if results.skipped:
            sigil = console.yellow("-")
            status = "skipped"
        elif results.exit_code == 0:
            sigil = console.green("✓")
            status = "succeeded"
        else:
            sigil = console.red("𐄂")
            status = "failed"
            exit_code = results.exit_code
        console.print_stderr(f"{sigil} {results.linter_name} {status}.")

    return Lint(exit_code)


# NB: We mark this uncachable to ensure that the results are always streamed, even if the
# underlying LintResults is memoized. This rule is very cheap, so there's little performance hit.
@_uncacheable_rule(desc="lint")
def enrich_lint_results(results: LintResults) -> EnrichedLintResults:
    return EnrichedLintResults(results=results.results, linter_name=results.linter_name)


def rules():
    return collect_rules()
