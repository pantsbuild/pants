# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from textwrap import dedent
from typing import ClassVar, List

import pytest

from pants.backend.project_info.paths import PathsGoal
from pants.backend.project_info.paths import rules as paths_rules
from pants.backend.python.macros import python_requirements
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
from pants.backend.python.target_types import PexBinary
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import Dependencies, OptionalSingleSourceField, Target
from pants.testutil.rule_runner import RuleRunner


class MockSourceField(OptionalSingleSourceField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".txt",)


class MockDepsField(Dependencies):
    pass


class MockTarget(Target):
    alias = "tgt"
    core_fields = (
        MockSourceField,
        MockDepsField,
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    runner = RuleRunner(
        rules=(
            *paths_rules(),
            *python_requirements.rules(),
        ),
        target_types=[MockTarget, PexBinary, PythonRequirementsTargetGenerator],
    )
    runner.write_files(
        {
            "base/base.txt": "",
            "base/BUILD": "tgt(source='base.txt')",
            "base/subdir/base-subdir.txt": "",
            "base/subdir/BUILD": "tgt(source='base-subdir.txt')",
            "intermediate/intermediate.txt": "",
            "intermediate/BUILD": "tgt(source='intermediate.txt', dependencies=['base'])",
            "intermediate2/BUILD": "tgt(dependencies=['base'])",
            "leaf/BUILD": "tgt(dependencies=['intermediate', 'intermediate2'])",
            "leaf/subdir/BUILD": "tgt(dependencies=['base/subdir', 'base'])",
            "island/BUILD": "tgt()",
            "3rdparty/BUILD": dedent(
                """\
                python_requirements(
                  overrides={
                    "lib": {
                      "dependencies": ("#lib-pluginA", "#lib-pluginB"),
                    },
                  },
                )
                """
            ),
            "3rdparty/requirements.txt": dedent(
                """\
                lib
                lib-pluginA
                lib-pluginB
                """
            ),
            "src/prj/a/BUILD": "pex_binary(dependencies=['3rdparty#lib', '!!3rdparty#lib-pluginA'])",
            "src/prj/b/BUILD": "pex_binary(dependencies=['3rdparty#lib'])",
        }
    )
    return runner


def assert_paths(
    rule_runner: RuleRunner,
    *,
    path_from: str,
    path_to: str,
    expected: List[List[str]] | None = None,
) -> None:
    args = []
    if path_from:
        args += [f"--paths-from={path_from}"]
    if path_to:
        args += [f"--paths-to={path_to}"]

    result = rule_runner.run_goal_rule(PathsGoal, args=[*args])

    if expected is not None:
        print(sorted(json.loads(result.stdout)))
        assert sorted(json.loads(result.stdout)) == sorted(expected)


def test_no_from(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError, match="Must set --from"):
        assert_paths(rule_runner, path_from="", path_to="base:base")


def test_no_to(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError, match="Must set --to"):
        assert_paths(rule_runner, path_from="intermediate:intermediate", path_to="")


@pytest.mark.parametrize(
    "path_from,path_to",
    [["intermediate:intermediate", "island:island"], ["island:island", "base:base"]],
)
def test_no_paths(rule_runner: RuleRunner, path_from: str, path_to: str) -> None:
    assert_paths(rule_runner, path_from=path_from, path_to=path_to, expected=[])


def test_normal(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="intermediate:intermediate",
        path_to="base:base",
        expected=[["intermediate:intermediate", "base:base"]],
    )


def test_normal_with_filesystem_specs(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="intermediate/intermediate.txt",
        path_to="base/base.txt",
        expected=[["intermediate:intermediate", "base:base"]],
    )


def test_path_to_self(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="base:base",
        path_to="base:base",
        expected=[["base:base"]],
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


def test_paths_from_multiple_to_multiple(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="leaf::",
        path_to="base::",
        expected=[
            ["leaf/subdir:subdir", "base/subdir:subdir"],
            ["leaf/subdir:subdir", "base:base"],
            ["leaf:leaf", "intermediate2:intermediate2", "base:base"],
            ["leaf:leaf", "intermediate:intermediate", "base:base"],
        ],
    )


def test_paths_from_single_to_multiple(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="leaf/subdir:subdir",
        path_to="base::",
        expected=[
            ["leaf/subdir:subdir", "base/subdir:subdir"],
            ["leaf/subdir:subdir", "base:base"],
        ],
    )


def test_paths_from_multiple_to_single(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="leaf::",
        path_to="base:base",
        expected=[
            ["leaf/subdir:subdir", "base:base"],
            ["leaf:leaf", "intermediate2:intermediate2", "base:base"],
            ["leaf:leaf", "intermediate:intermediate", "base:base"],
        ],
    )


def test_excluded_paths(rule_runner: RuleRunner) -> None:
    assert_paths(
        rule_runner,
        path_from="src/prj/a",
        path_to="src/prj/b",
        expected=[],
    )
