# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Iterable, TypeVar, cast

from pants.core.goals.lint import REPORT_DIR as REPORT_DIR  # noqa: F401
from pants.core.goals.multi_tool_goal_helper import (
    OnlyOption,
    determine_specified_tool_ids,
    write_reports,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, Digest, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, QueryRule, collect_rules, goal_rule
from pants.engine.target import FieldSet, FilteredTargets
from pants.engine.unions import UnionMembership, union
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import classproperty
from pants.util.strutil import Simplifier

logger = logging.getLogger(__name__)

_FS = TypeVar("_FS", bound=FieldSet)


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
        output_simplifier: Simplifier = Simplifier(),
        report: Digest = EMPTY_DIGEST,
    ) -> CheckResult:
        return CheckResult(
            exit_code=process_result.exit_code,
            stdout=output_simplifier.simplify(process_result.stdout),
            stderr=output_simplifier.simplify(process_result.stderr),
            partition_description=partition_description,
            report=report,
        )

    def metadata(self) -> dict[str, Any]:
        return {"partition": self.partition_description}


@dataclass(frozen=True)
class CheckResults(EngineAwareReturnType):
    """Zero or more CheckResult objects for a single type checker.

    Typically, type checkers will return one result. If they no-oped, they will return zero results.
    However, some type checkers may need to partition their input and thus may need to return
    multiple results.
    """

    results: tuple[CheckResult, ...]
    checker_name: str

    def __init__(self, results: Iterable[CheckResult], *, checker_name: str) -> None:
        object.__setattr__(self, "results", tuple(results))
        object.__setattr__(self, "checker_name", checker_name)

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


@dataclass(frozen=True)
@union(in_scope_types=[EnvironmentName])
class CheckRequest(Generic[_FS], EngineAwareParameter):
    """A union for targets that should be checked.

    Subclass and install a member of this type to provide a checker.
    """

    field_set_type: ClassVar[type[_FS]]  # type: ignore[misc]
    tool_name: ClassVar[str]

    @classproperty
    def tool_id(cls) -> str:
        """The "id" of the tool, used in tool selection (Eg --only=<id>)."""
        return cls.tool_name

    field_sets: Collection[_FS]

    def __init__(self, field_sets: Iterable[_FS]) -> None:
        object.__setattr__(self, "field_sets", Collection[_FS](field_sets))

    def debug_hint(self) -> str:
        return self.tool_name

    def metadata(self) -> dict[str, Any]:
        return {"addresses": [fs.address.spec for fs in self.field_sets]}


class CheckSubsystem(GoalSubsystem):
    name = "check"
    help = "Run type checking or the lightest variant of compilation available for a language."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return CheckRequest in union_membership

    only = OnlyOption("checker", "mypy", "javac")


class Check(Goal):
    subsystem_cls = CheckSubsystem
    environment_behavior = Goal.EnvironmentBehavior.USES_ENVIRONMENTS


@goal_rule
async def check(
    console: Console,
    workspace: Workspace,
    targets: FilteredTargets,
    dist_dir: DistDir,
    union_membership: UnionMembership,
    check_subsystem: CheckSubsystem,
) -> Check:
    request_types = cast("Iterable[type[CheckRequest]]", union_membership[CheckRequest])
    specified_ids = determine_specified_tool_ids("check", check_subsystem.only, request_types)

    requests = tuple(
        request_type(
            request_type.field_set_type.create(target)
            for target in targets
            if (
                request_type.tool_id in specified_ids
                and request_type.field_set_type.is_applicable(target)
            )
        )
        for request_type in request_types
    )

    request_to_field_set = [
        (request, field_set) for request in requests for field_set in request.field_sets
    ]

    environment_names = await MultiGet(
        Get(
            EnvironmentName,
            EnvironmentNameRequest,
            EnvironmentNameRequest.from_field_set(field_set),
        )
        for (_, field_set) in request_to_field_set
    )

    request_to_env_name = {
        (request, env_name)
        for (request, _), env_name in zip(request_to_field_set, environment_names)
    }

    # Run each check request in each valid environment (potentially multiple runs per tool)
    all_results = await MultiGet(
        Get(CheckResults, {request: CheckRequest, env_name: EnvironmentName})
        for (request, env_name) in request_to_env_name
    )

    results_by_tool: dict[str, list[CheckResult]] = defaultdict(list)
    for results in all_results:
        results_by_tool[results.checker_name].extend(results.results)

    write_reports(
        results_by_tool,
        workspace,
        dist_dir,
        goal_name=CheckSubsystem.name,
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
