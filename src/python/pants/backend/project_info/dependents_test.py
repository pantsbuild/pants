# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

import pytest

from pants.backend.project_info.dependents import DependeesGoal
from pants.backend.project_info.dependents import rules as dependee_rules
from pants.engine.target import Dependencies, SpecialCasedDependencies, Target
from pants.testutil.rule_runner import RuleRunner


class SpecialDeps(SpecialCasedDependencies):
    alias = "special_deps"


class MockDepsField(Dependencies):
    pass


class MockTarget(Target):
    alias = "tgt"
    core_fields = (MockDepsField, SpecialDeps)


@pytest.fixture
def rule_runner() -> RuleRunner:
    runner = RuleRunner(rules=dependee_rules(), target_types=[MockTarget])
    runner.write_files(
        {
            "base/BUILD": "tgt()",
            "intermediate/BUILD": "tgt(dependencies=['base'])",
            "leaf/BUILD": "tgt(dependencies=['intermediate'])",
        }
    )
    return runner


def assert_dependents(
    rule_runner: RuleRunner,
    *,
    targets: List[str],
    expected: List[str],
    transitive: bool = False,
    closed: bool = False,
) -> None:
    args = []
    if transitive:
        args.append("--transitive")
    if closed:
        args.append("--closed")
    result = rule_runner.run_goal_rule(DependeesGoal, args=[*args, *targets])
    assert result.stdout.splitlines() == expected


def test_no_targets(rule_runner: RuleRunner) -> None:
    assert_dependents(rule_runner, targets=[], expected=[])


def test_normal(rule_runner: RuleRunner) -> None:
    assert_dependents(rule_runner, targets=["base"], expected=["intermediate:intermediate"])


def test_no_dependees(rule_runner: RuleRunner) -> None:
    assert_dependents(rule_runner, targets=["leaf"], expected=[])


def test_closed(rule_runner: RuleRunner) -> None:
    assert_dependents(rule_runner, targets=["leaf"], closed=True, expected=["leaf:leaf"])


def test_transitive(rule_runner: RuleRunner) -> None:
    assert_dependents(
        rule_runner,
        targets=["base"],
        transitive=True,
        expected=["intermediate:intermediate", "leaf:leaf"],
    )


def test_multiple_specified_targets(rule_runner: RuleRunner) -> None:
    # This tests that --output-format=text will deduplicate which dependee belongs to which
    # specified target.
    assert_dependents(
        rule_runner,
        targets=["base", "intermediate"],
        transitive=True,
        # NB: `intermediate` is not included because it's a root and we have `--no-closed`.
        expected=["leaf:leaf"],
    )


def test_special_cased_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"special/BUILD": "tgt(special_deps=['intermediate'])"})
    assert_dependents(
        rule_runner, targets=["intermediate"], expected=["leaf:leaf", "special:special"]
    )
    assert_dependents(
        rule_runner,
        targets=["base"],
        transitive=True,
        expected=["intermediate:intermediate", "leaf:leaf", "special:special"],
    )
