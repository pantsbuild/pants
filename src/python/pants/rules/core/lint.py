# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargetsWithOrigins
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.objects import Collection, union
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


class LintResults(Collection[LintResult]):
    """This collection allows us to aggregate multiple `LintResult`s for a language."""


@union
class LintTarget:
    """A union for registration of a lintable target type.

    The union members should be subclasses of TargetAdaptorWithOrigin.
    """

    @staticmethod
    def is_lintable(
        adaptor_with_origin: TargetAdaptorWithOrigin, *, union_membership: UnionMembership
    ) -> bool:
        is_lint_target = union_membership.is_member(LintTarget, adaptor_with_origin)
        return adaptor_with_origin.adaptor.has_sources() and is_lint_target


class LintOptions(GoalSubsystem):
    """Lint source code."""

    # TODO: make this "lint"
    # Blocked on https://github.com/pantsbuild/pants/issues/8351
    name = "lint2"

    required_union_implementations = (LintTarget,)


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
    nested_results = await MultiGet(
        Get[LintResults](LintTarget, adaptor_with_origin)
        for adaptor_with_origin in adaptors_with_origins
        if LintTarget.is_lintable(adaptor_with_origin, union_membership=union_membership)
    )
    results = list(itertools.chain.from_iterable(nested_results))

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
