# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from functools import partial
from typing import Dict, List, Optional, Union

import pytest

from pants.backend.project_info.dependents import DependentsGoal, DependentsOutputFormat
from pants.backend.project_info.dependents import rules as dependent_rules
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
    runner = RuleRunner(rules=dependent_rules(), target_types=[MockTarget])
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
    expected: Union[List[str], Dict[str, List[str]]],
    transitive: bool = False,
    output_file: Optional[str] = None,
    closed: bool = False,
    output_format: DependentsOutputFormat = DependentsOutputFormat.text,
) -> None:
    args = []
    if transitive:
        args.append("--transitive")
    if output_file:
        args.extend([f"--output-file={output_file}"])
    if closed:
        args.append("--closed")
    args.append(f"--format={output_format.value}")
    result = rule_runner.run_goal_rule(DependentsGoal, args=[*args, *targets])

    if output_file is None:
        if output_format == DependentsOutputFormat.text:
            assert result.stdout.splitlines() == expected
        elif output_format == DependentsOutputFormat.json:
            assert json.loads(result.stdout) == expected
    else:
        assert not result.stdout
        with rule_runner.pushd():
            with open(output_file) as f:
                if output_format == DependentsOutputFormat.text:
                    assert f.read().splitlines() == expected
                elif output_format == DependentsOutputFormat.json:
                    assert json.load(f) == expected


def test_no_targets(rule_runner: RuleRunner) -> None:
    assert_dependents(rule_runner, targets=[], expected=[])


def test_normal(rule_runner: RuleRunner) -> None:
    assert_dependents(rule_runner, targets=["base"], expected=["intermediate:intermediate"])


def test_no_dependents(rule_runner: RuleRunner) -> None:
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
    # This tests that --output-format=text will deduplicate which dependent belongs to which
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


def test_dependents_as_json_direct_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"special/BUILD": "tgt(special_deps=['intermediate'])"})
    assert_deps = partial(
        assert_dependents,
        rule_runner,
        output_format=DependentsOutputFormat.json,
    )
    # input: single target
    assert_deps(
        targets=["base"],
        transitive=False,
        expected={
            "base:base": ["intermediate:intermediate"],
        },
    )

    # input: multiple targets
    assert_deps(
        targets=["base", "intermediate"],
        transitive=False,
        expected={
            "base:base": ["intermediate:intermediate"],
            "intermediate:intermediate": ["leaf:leaf", "special:special"],
        },
    )

    # input: all targets
    assert_deps(
        targets=["::"],
        transitive=False,
        expected={
            "base:base": ["intermediate:intermediate"],
            "intermediate:intermediate": ["leaf:leaf", "special:special"],
            "leaf:leaf": [],
            "special:special": [],
        },
    )

    # input: all targets, closed
    assert_deps(
        targets=["::"],
        transitive=False,
        closed=True,
        expected={
            "base:base": ["base:base", "intermediate:intermediate"],
            "intermediate:intermediate": [
                "intermediate:intermediate",
                "leaf:leaf",
                "special:special",
            ],
            "leaf:leaf": ["leaf:leaf"],
            "special:special": ["special:special"],
        },
    )

    # input: single target with output file
    assert_deps(
        targets=["base"],
        transitive=False,
        output_file="output.json",
        expected={
            "base:base": ["intermediate:intermediate"],
        },
    )


def test_dependents_as_json_transitive_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"special/BUILD": "tgt(special_deps=['intermediate'])"})
    assert_deps = partial(
        assert_dependents,
        rule_runner,
        output_format=DependentsOutputFormat.json,
    )

    # input: single target
    assert_deps(
        targets=["base"],
        transitive=True,
        expected={
            "base:base": ["intermediate:intermediate", "leaf:leaf", "special:special"],
        },
    )

    # input: multiple targets
    assert_deps(
        targets=["base", "intermediate"],
        transitive=True,
        expected={
            "base:base": ["intermediate:intermediate", "leaf:leaf", "special:special"],
            "intermediate:intermediate": ["leaf:leaf", "special:special"],
        },
    )

    # input: all targets
    assert_deps(
        targets=["::"],
        transitive=True,
        expected={
            "base:base": ["intermediate:intermediate", "leaf:leaf", "special:special"],
            "intermediate:intermediate": ["leaf:leaf", "special:special"],
            "leaf:leaf": [],
            "special:special": [],
        },
    )

    # input: all targets, closed
    assert_deps(
        targets=["::"],
        transitive=True,
        closed=True,
        expected={
            "base:base": ["base:base", "intermediate:intermediate", "leaf:leaf", "special:special"],
            "intermediate:intermediate": [
                "intermediate:intermediate",
                "leaf:leaf",
                "special:special",
            ],
            "leaf:leaf": ["leaf:leaf"],
            "special:special": ["special:special"],
        },
    )
