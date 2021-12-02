# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from typing import List

import pytest

from pants.backend.project_info.paths import PathsGoal
from pants.backend.project_info.paths import rules as paths_rules
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import Dependencies, Target
from pants.testutil.rule_runner import RuleRunner


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Dependencies,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    runner = RuleRunner(rules=paths_rules(), target_types=[MockTarget])
    runner.add_to_build_file("base", "tgt()")
    runner.add_to_build_file("intermediate", "tgt(dependencies=['base'])")
    runner.add_to_build_file("intermediate2", "tgt(dependencies=['base'])")
    runner.add_to_build_file("leaf", "tgt(dependencies=['intermediate', 'intermediate2'])")
    return runner


def assert_paths(
    rule_runner: RuleRunner,
    *,
    path_from: str,
    path_to: str,
    expected: List[List[str]],
) -> None:
    args = []
    if path_from:
        args += [f"--path-from={path_from}"]
    if path_to:
        args += [f"--path-to={path_to}"]

    result = rule_runner.run_goal_rule(PathsGoal, args=[*args])
    import sys

    print(result.stdout, file=sys.stderr)
    assert sorted(json.loads(result.stdout)) == sorted(expected)


@pytest.mark.parametrize(
    "path_from,path_to", [["", ""], ["intermediate:intermediate", ""], ["", "base:base"]]
)
def test_no_targets(rule_runner: RuleRunner, path_from: str, path_to: str) -> None:
    with pytest.raises(ExecutionError):
        assert_paths(rule_runner, path_from=path_from, path_to=path_to, expected=[])


def test_normal(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="intermediate:intermediate",
        path_to="base:base",
        expected=[["intermediate:intermediate", "base:base"]],
    )


def test_multiple_paths(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="leaf:leaf",
        path_to="base:base",
        expected=[
            ["leaf:leaf", "intermediate:intermediate", "base:base"],
            ["leaf:leaf", "intermediate2:intermediate2", "base:base"],
        ],
    )
