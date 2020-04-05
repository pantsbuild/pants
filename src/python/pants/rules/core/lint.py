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
    __slots__ = ("exit_code", "stdout", "stderr")

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
    def is_valid_target(_: TargetAdaptorWithOrigin) -> bool:
        """Return True if the linter can meaningfully operate on this target type."""


class LintOptions(GoalSubsystem):
    """Lint source code."""

    name = "lint"

    required_union_implementations = (Linter,)

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
                "separate process. Why do this? You'll get many more cache hits. Additionally, for "
                "Python users, if you have some targets that only work with Python 2 and some that "
                "only work with Python 3, `--per-target-caching` will allow you to use the right "
                "interpreter for each target. Why not do this? Linters both have substantial "
                "startup overhead and are cheap to add one additional file to the run. On a cold "
                "cache, it is much faster to use `--no-per-target-caching`. We only recommend "
                "using `--per-target-caching` if you "
                "are using a remote cache, or if you have some Python 2-only targets and "
                "some Python 3-only targets, or if you have benchmarked that this option will be "
                "faster than `--no-per-target-caching` for your use case."
            ),
        )


class Lint(Goal):
    subsystem_cls = LintOptions


@goal_rule
async def lint(
    console: Console,
    targets_with_origins: HydratedTargetsWithOrigins,
    options: LintOptions,
    union_membership: UnionMembership,
) -> Lint:
    adaptors_with_origins = tuple(
        TargetAdaptorWithOrigin.create(target_with_origin.target.adaptor, target_with_origin.origin)
        for target_with_origin in targets_with_origins
        if target_with_origin.target.adaptor.has_sources()
    )

    linters: Iterable[Type[Linter]] = union_membership.union_rules[Linter]
    if options.values.per_target_caching:
        results = await MultiGet(
            Get[LintResult](Linter, linter((adaptor_with_origin,)))
            for adaptor_with_origin in adaptors_with_origins
            for linter in linters
            if linter.is_valid_target(adaptor_with_origin)
        )
    else:
        linters_with_valid_targets = {
            linter: tuple(
                adaptor_with_origin
                for adaptor_with_origin in adaptors_with_origins
                if linter.is_valid_target(adaptor_with_origin)
            )
            for linter in linters
        }
        results = await MultiGet(
            Get[LintResult](Linter, linter(valid_targets))
            for linter, valid_targets in linters_with_valid_targets.items()
            if valid_targets
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
