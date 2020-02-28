# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Tuple, Type

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargetsWithOrigins
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.selectors import Get, MultiGet


@dataclass(frozen=True)
class LintResult:
    exit_code: int
    stdout: str
    stderr: str

    @staticmethod
    def noop() -> "LintResult":
        return LintResult(exit_code=0, stdout="", stderr="")

    @staticmethod
    def from_fallible_execute_process_result(
        process_result: FallibleExecuteProcessResult,
    ) -> "LintResult":
        return LintResult(
            exit_code=process_result.exit_code,
            stdout=process_result.stdout.decode(),
            stderr=process_result.stderr.decode(),
        )


@union
@dataclass(frozen=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
class Linter(ABC):
    adaptors_with_origins: Tuple[TargetAdaptorWithOrigin, ...]

    @staticmethod
    @abstractmethod
    def is_valid_target(adaptor_with_origin: TargetAdaptorWithOrigin) -> bool:
        """Return True if the linter can meaningfully operate on this target type."""


class LintOptions(GoalSubsystem):
    """Lint source code."""

    # TODO: make this "lint"
    # Blocked on https://github.com/pantsbuild/pants/issues/8351
    name = "lint2"

    required_union_implementations = (Linter,)


class Lint(Goal):
    subsystem_cls = LintOptions


@goal_rule
async def lint(
    console: Console,
    targets_with_origins: HydratedTargetsWithOrigins,
    union_membership: UnionMembership,
) -> Lint:
    adaptors_with_origins = [
        TargetAdaptorWithOrigin.create(target_with_origin.target.adaptor, target_with_origin.origin)
        for target_with_origin in targets_with_origins
    ]

    linters: Iterable[Type[Linter]] = union_membership.union_rules[Linter]
    results = await MultiGet(
        Get[LintResult](Linter, linter((adaptor_with_origin,)))
        for adaptor_with_origin in adaptors_with_origins
        for linter in linters
        if adaptor_with_origin.adaptor.has_sources() and linter.is_valid_target(adaptor_with_origin)
    )

    if not results:
        return Lint(exit_code=0)

    exit_code = 0
    for result in results:
        if result.stdout:
            console.print_stdout(result.stdout)
        if result.stderr:
            console.print_stderr(result.stderr)
        if result.exit_code != 0:
            exit_code = result.exit_code

    return Lint(exit_code)


def rules():
    return [lint]
