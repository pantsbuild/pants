# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List

import pytest

from pants.backend.project_info.dependees import DependeesGoal
from pants.backend.project_info.dependees import DependeesOutputFormat as OutputFormat
from pants.backend.project_info.dependees import rules as dependee_rules
from pants.engine.target import Dependencies, SpecialCasedDependencies, Target
from pants.testutil.rule_runner import RuleRunner


class SpecialDeps(SpecialCasedDependencies):
    alias = "special_deps"


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Dependencies, SpecialDeps)


@pytest.fixture
def rule_runner() -> RuleRunner:
    runner = RuleRunner(rules=dependee_rules(), target_types=[MockTarget])
    runner.add_to_build_file("base", "tgt()")
    runner.add_to_build_file("intermediate", "tgt(dependencies=['base'])")
    runner.add_to_build_file("leaf", "tgt(dependencies=['intermediate'])")
    return runner


def assert_dependees(
    rule_runner: RuleRunner,
    *,
    targets: List[str],
    expected: List[str],
    transitive: bool = False,
    closed: bool = False,
    output_format: OutputFormat = OutputFormat.text,
) -> None:
    args = [f"--output-format={output_format.value}"]
    if transitive:
        args.append("--transitive")
    if closed:
        args.append("--closed")
    result = rule_runner.run_goal_rule(DependeesGoal, args=[*args, *targets])
    assert result.stdout.splitlines() == expected


def test_no_targets(rule_runner: RuleRunner) -> None:
    assert_dependees(rule_runner, targets=[], expected=[])
    assert_dependees(rule_runner, targets=[], output_format=OutputFormat.json, expected=["{}"])


def test_normal(rule_runner: RuleRunner) -> None:
    assert_dependees(rule_runner, targets=["base"], expected=["intermediate"])
    assert_dependees(
        rule_runner,
        targets=["base"],
        output_format=OutputFormat.json,
        expected=dedent(
            """\
            {
                "base": [
                    "intermediate"
                ]
            }"""
        ).splitlines(),
    )


def test_no_dependees(rule_runner: RuleRunner) -> None:
    assert_dependees(rule_runner, targets=["leaf"], expected=[])
    assert_dependees(
        rule_runner,
        targets=["leaf"],
        output_format=OutputFormat.json,
        expected=dedent(
            """\
            {
                "leaf": []
            }"""
        ).splitlines(),
    )


def test_closed(rule_runner: RuleRunner) -> None:
    assert_dependees(rule_runner, targets=["leaf"], closed=True, expected=["leaf"])
    assert_dependees(
        rule_runner,
        targets=["leaf"],
        closed=True,
        output_format=OutputFormat.json,
        expected=dedent(
            """\
            {
                "leaf": [
                    "leaf"
                ]
            }"""
        ).splitlines(),
    )


def test_transitive(rule_runner: RuleRunner) -> None:
    assert_dependees(
        rule_runner, targets=["base"], transitive=True, expected=["intermediate", "leaf"]
    )
    assert_dependees(
        rule_runner,
        targets=["base"],
        transitive=True,
        output_format=OutputFormat.json,
        expected=dedent(
            """\
            {
                "base": [
                    "intermediate",
                    "leaf"
                ]
            }"""
        ).splitlines(),
    )


def test_multiple_specified_targets(rule_runner: RuleRunner) -> None:
    # This tests that --output-format=text will deduplicate and that --output-format=json will
    # preserve which dependee belongs to which specified target.
    assert_dependees(
        rule_runner,
        targets=["base", "intermediate"],
        transitive=True,
        # NB: `intermediate` is not included because it's a root and we have `--no-closed`.
        expected=["leaf"],
    )
    assert_dependees(
        rule_runner,
        targets=["base", "intermediate"],
        transitive=True,
        output_format=OutputFormat.json,
        expected=dedent(
            """\
            {
                "base": [
                    "intermediate",
                    "leaf"
                ],
                "intermediate": [
                    "leaf"
                ]
            }"""
        ).splitlines(),
    )


def test_special_cased_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("special", "tgt(special_deps=['intermediate'])")
    assert_dependees(rule_runner, targets=["intermediate"], expected=["leaf", "special"])
    assert_dependees(
        rule_runner, targets=["base"], transitive=True, expected=["intermediate", "leaf", "special"]
    )
