# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pants.backend.visibility.rules import SkipVisibilityValidation, skip_visibility_validation
from pants.engine.goal import CurrentExecutingGoals, Goal, GoalSubsystem
from pants.engine.rules import goal_rule, rule
from pants.testutil.rule_runner import RuleRunner, run_rule_with_mocks


@pytest.mark.parametrize(
    "requested, skip",
    [
        (("lint",), True),
        (("lint", "test"), False),
        (("test", "lint"), False),
        (("test",), False),
        ((), False),
    ],
)
def test_skip_visibility_validation(requested: tuple[str, ...], skip: bool) -> None:
    result = run_rule_with_mocks(
        skip_visibility_validation, rule_args=[CurrentExecutingGoals(requested=requested)]
    )
    assert result == SkipVisibilityValidation(skip)


class DummyGoalOptions(GoalSubsystem):
    name = "dummy"
    help = "dummy help"


class DummyGoal(Goal):
    subsystem_cls = DummyGoalOptions
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@dataclass(frozen=True)
class Consumed:
    skip: bool


consumer_calls: list[bool] = []


@rule
async def consumer(skip: SkipVisibilityValidation) -> Consumed:
    consumer_calls.append(skip.value)
    return Consumed(skip.value)


@goal_rule
async def dummy_goal(consumed: Consumed) -> DummyGoal:
    return DummyGoal(0)


def test_skip_visibility_validation_reused_across_sessions() -> None:
    consumer_calls.clear()
    rule_runner = RuleRunner(rules=[skip_visibility_validation, consumer, dummy_goal])

    def run(requested: tuple[str, ...]) -> None:
        rule_runner.set_session_values(
            {CurrentExecutingGoals: CurrentExecutingGoals(requested=requested)}
        )
        assert rule_runner.run_goal_rule(DummyGoal).exit_code == 0

    # `CurrentExecutingGoals` changes between sessions, but the decision derived from it doesn't,
    # so its consumers are reused.
    run(("dummy",))
    run(("dummy",))
    assert consumer_calls == [False]

    run(("lint",))
    assert consumer_calls == [False, True]
