# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.mixed_interpreter_constraints.py_constraints import PyConstraintsGoal
from pants.backend.python.mixed_interpreter_constraints.py_constraints import (
    rules as py_constraints_rules,
)
from pants.backend.python.target_types import PythonLibrary, PythonTests
from pants.core.target_types import Files
from pants.testutil.rule_runner import GoalRuleResult, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=py_constraints_rules(), target_types=[Files, PythonLibrary, PythonTests]
    )


def write_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "lib1/BUILD": "python_library(sources=[], interpreter_constraints=['==2.7.*', '>=3.5'])",
            # We leave off `interpreter_constraints`, which results in using
            # `[python-setup].interpreter_constraints` instead. Also, we create files so that we
            # can test how file addresses render.
            "lib2/a.py": "",
            "lib2/b.py": "",
            "lib2/BUILD": "python_library()",
            "app/BUILD": dedent(
                """\
                python_library(
                    sources=[],
                    dependencies=['lib1', 'lib2/a.py', 'lib2/b.py'],
                    interpreter_constraints=['==3.7.*'],
                )
                """
            ),
        }
    )


def run_goal(rule_runner: RuleRunner, args: list[str]) -> GoalRuleResult:
    return rule_runner.run_goal_rule(
        PyConstraintsGoal,
        env={"PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS": "['>=3.6']"},
        args=args,
    )


def test_no_matches(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.write_files({"f.txt": "", "BUILD": "files(name='tgt', sources=['f.txt'])"})
    result = run_goal(rule_runner, ["f.txt"])
    assert result.exit_code == 0
    assert len(caplog.records) == 1
    assert (
        "No Python files/targets matched for the `py-constraints` goal. All target types with "
        "Python interpreter constraints: python_library, python_tests"
    ) in caplog.text


def test_render_constraints(rule_runner: RuleRunner) -> None:
    write_files(rule_runner)
    result = run_goal(rule_runner, ["app"])
    assert result.stdout == dedent(
        """\
        Final merged constraints: CPython==2.7.*,==3.7.*,>=3.6 OR CPython==3.7.*,>=3.5,>=3.6

        CPython==3.7.*
          app

        CPython>=3.6
          lib2/a.py
          lib2/b.py

        CPython==2.7.* OR CPython>=3.5
          lib1
        """
    )

    # If we run on >1 input, we include a warning about what the "final merged constraints" mean.
    result = run_goal(rule_runner, ["app", "lib1"])
    assert "Consider using a more precise query" in result.stdout


def test_constraints_summary(rule_runner: RuleRunner) -> None:
    write_files(rule_runner)
    result = run_goal(rule_runner, ["--summary"])
    assert result.stdout == dedent(
        """\
        Target,Constraints,Transitive Constraints,# Dependencies,# Dependees\r
        app,CPython==3.7.*,"CPython==2.7.*,==3.7.*,>=3.6 OR CPython==3.7.*,>=3.5,>=3.6",3,0\r
        lib1,CPython==2.7.* OR CPython>=3.5,CPython==2.7.* OR CPython>=3.5,0,1\r
        lib2,CPython>=3.6,CPython>=3.6,2,0\r
        lib2/a.py,CPython>=3.6,CPython>=3.6,2,3\r
        lib2/b.py,CPython>=3.6,CPython>=3.6,2,3\r
        """
    )
