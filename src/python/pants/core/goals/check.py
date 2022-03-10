# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, cast

from pants.core.goals.lint import REPORT_DIR as REPORT_DIR  # noqa: F401
from pants.core.goals.style_request import (
    StyleRequest,
    determine_specified_tool_names,
    only_option_help,
    write_reports,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, Digest, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, QueryRule, collect_rules, goal_rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import StrListOption
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.strutil import strip_v2_chroot_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    exit_code: int
    stdout: str
    stderr: str
    partition_description: str | None = None
    report: Digest = EMPTY_DIGEST

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult,
        *,
        partition_description: str | None = None,
        strip_chroot_path: bool = False,
        report: Digest = EMPTY_DIGEST,
    ) -> CheckResult:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return CheckResult(
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
class CheckResults(EngineAwareReturnType):
    """Zero or more CheckResult objects for a single type checker.

    Typically, type checkers will return one result. If they no-oped, they will return zero results.
    However, some type checkers may need to partition their input and thus may need to return
    multiple results.
    """

    results: tuple[CheckResult, ...]
    checker_name: str

    def __init__(self, results: Iterable[CheckResult], *, checker_name: str) -> None:
        self.results = tuple(results)
        self.checker_name = checker_name

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
            return f"{self.checker_name} skipped."
        message = self.checker_name
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )

        def msg_for_result(result: CheckResult) -> str:
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
class CheckRequest(StyleRequest):
    """A union for StyleRequests that should be type-checkable.

    Subclass and install a member of this type to provide a linter.
    """


class CheckSubsystem(GoalSubsystem):
    name = "check"
    help = "Run type checking or the lightest variant of compilation available for a language."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return CheckRequest in union_membership

    only = StrListOption(
        "--only",
        help=only_option_help("check", "checkers", "mypy", "javac"),
    )


class Check(Goal):
    subsystem_cls = CheckSubsystem


@goal_rule
async def check(
    console: Console,
    workspace: Workspace,
    targets: Targets,
    dist_dir: DistDir,
    union_membership: UnionMembership,
    check_subsystem: CheckSubsystem,
) -> Check:
    request_types = cast("Iterable[type[StyleRequest]]", union_membership[CheckRequest])
    specified_names = determine_specified_tool_names("check", check_subsystem.only, request_types)

    requests = tuple(
        request_type(
            request_type.field_set_type.create(target)
            for target in targets
            if (
                request_type.name in specified_names
                and request_type.field_set_type.is_applicable(target)
            )
        )
        for request_type in request_types
    )
    all_results = await MultiGet(
        Get(CheckResults, CheckRequest, request) for request in requests if request.field_sets
    )

    def get_name(res: CheckResults) -> str:
        return res.checker_name

    write_reports(
        all_results,
        workspace,
        dist_dir,
        goal_name=CheckSubsystem.name,
        get_name=get_name,
    )

    exit_code = 0
    if all_results:
        console.print_stderr("")
    for results in sorted(all_results, key=lambda results: results.checker_name):
        if results.skipped:
            continue
        elif results.exit_code == 0:
            sigil = console.sigil_succeeded()
            status = "succeeded"
        else:
            sigil = console.sigil_failed()
            status = "failed"
            exit_code = results.exit_code
        console.print_stderr(f"{sigil} {results.checker_name} {status}.")

    return Check(exit_code)


def rules():
    return [
        *collect_rules(),
        # NB: Would be unused otherwise.
        QueryRule(CheckSubsystem, []),
    ]
