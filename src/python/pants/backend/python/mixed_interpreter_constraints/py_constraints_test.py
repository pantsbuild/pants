# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.python.mixed_interpreter_constraints.py_constraints import PyConstraintsGoal
from pants.backend.python.mixed_interpreter_constraints.py_constraints import (
    rules as py_constraints_rules,
)
from pants.backend.python.target_types import PythonLibrary
from pants.core.target_types import Files
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=py_constraints_rules(), target_types=[Files, PythonLibrary])


def test_no_matches(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.create_file("f.txt")
    rule_runner.add_to_build_file("", "files(name='tgt', sources=['f.txt'])")
    result = rule_runner.run_goal_rule(PyConstraintsGoal, args=["f.txt"])
    assert result.exit_code == 0
    assert len(caplog.records) == 1
    assert "No Python files/targets matched" in caplog.text


def test_render_constraints(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "lib1", "python_library(sources=[], interpreter_constraints=['==2.7.*', '>=3.5'])"
    )

    # We leave off `interpreter_constraints`, which results in using
    # `[python-setup].interpreter_constraints` instead. Also, we create files so that we can test
    # how file addresses render.
    rule_runner.create_file("lib2/a.py")
    rule_runner.create_file("lib2/b.py")
    rule_runner.add_to_build_file("lib2", "python_library()")

    rule_runner.add_to_build_file(
        "app",
        dedent(
            """\
            python_library(
              sources=[],
              dependencies=['lib1', 'lib2/a.py', 'lib2/b.py'],
              interpreter_constraints=['==3.7.*'],
            )
            """
        ),
    )

    rule_runner.set_options(["--python-setup-interpreter-constraints=['>=3.6']"])

    result = rule_runner.run_goal_rule(PyConstraintsGoal, args=["app"])
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
