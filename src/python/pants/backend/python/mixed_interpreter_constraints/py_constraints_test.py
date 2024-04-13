# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.mixed_interpreter_constraints.py_constraints import PyConstraintsGoal
from pants.backend.python.mixed_interpreter_constraints.py_constraints import (
    rules as py_constraints_rules,
)
from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.core.target_types import FileTarget
from pants.testutil.rule_runner import GoalRuleResult, RuleRunner
from pants.util.strutil import softwrap


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(*py_constraints_rules(), *target_types_rules.rules()),
        target_types=[
            FileTarget,
            PythonSourcesGeneratorTarget,
            PythonTestsGeneratorTarget,
            PythonSourceTarget,
            PythonTestTarget,
        ],
    )


def write_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "lib1/f.py": "",
            "lib1/BUILD": "python_sources(interpreter_constraints=['==2.7.*', '>=3.5'])",
            # We leave off `interpreter_constraints`, which results in using
            # `[python].interpreter_constraints` instead.
            "lib2/f.py": "",
            "lib2/BUILD": "python_sources()",
            "app/f.py": "",
            "app/BUILD": dedent(
                """\
                python_sources(
                    dependencies=['lib1', 'lib2/f.py'],
                    interpreter_constraints=['==3.7.*'],
                )
                """
            ),
        }
    )


def run_goal(rule_runner: RuleRunner, args: list[str]) -> GoalRuleResult:
    return rule_runner.run_goal_rule(
        PyConstraintsGoal,
        env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": "['>=3.6']"},
        args=args,
        global_args=["--no-python-infer-imports"],
    )


def test_no_matches(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.write_files({"f.txt": "", "BUILD": "file(name='tgt', source='f.txt')"})
    result = run_goal(rule_runner, ["f.txt"])
    assert result.exit_code == 0
    print(caplog.records)
    assert len(caplog.records) == 1
    assert (
        softwrap(
            """
            No Python files/targets matched for the `py-constraints` goal. All target types with
            Python interpreter constraints: python_source, python_test
            """
        )
        in caplog.text
    )


def test_render_constraints(rule_runner: RuleRunner) -> None:
    write_files(rule_runner)
    result = run_goal(rule_runner, ["app:app"])
    assert result.stdout == dedent(
        """\
        Final merged constraints: CPython==2.7.*,==3.7.*,>=3.6 OR CPython==3.7.*,>=3.5,>=3.6

        CPython==3.7.*
          app/f.py

        CPython>=3.6
          lib2/f.py

        CPython==2.7.* OR CPython>=3.5
          lib1/f.py
        """
    )

    # If we run on >1 input, we include a warning about what the "final merged constraints" mean.
    result = run_goal(rule_runner, ["app:app", "lib1:lib1"])
    assert "Consider using a more precise query" in result.stdout


def test_constraints_summary(rule_runner: RuleRunner) -> None:
    write_files(rule_runner)
    result = run_goal(rule_runner, ["--summary"])
    assert result.stdout == dedent(
        """\
        Target,Constraints,Transitive Constraints,# Dependencies,# Dependents\r
        app/f.py,CPython==3.7.*,"CPython==2.7.*,==3.7.*,>=3.6 OR CPython==3.7.*,>=3.5,>=3.6",2,1\r
        lib1/f.py,CPython==2.7.* OR CPython>=3.5,CPython==2.7.* OR CPython>=3.5,0,3\r
        lib2/f.py,CPython>=3.6,CPython>=3.6,0,3\r
        """
    )
