# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.experimental.python.lockfile import PythonLockfileRequest
from pants.backend.python.lint.black import skip_field
from pants.backend.python.lint.black.subsystem import Black, BlackLockfileSentinel
from pants.backend.python.lint.black.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import PythonLibrary
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.target_types import GenericTarget
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_setup_lockfile_interpreter_constraints() -> None:
    rule_runner = RuleRunner(
        rules=[
            *subsystem_rules(),
            *skip_field.rules(),
            QueryRule(PythonLockfileRequest, [BlackLockfileSentinel]),
        ],
        target_types=[PythonLibrary, GenericTarget],
    )

    global_constraint = "==3.9.*"
    rule_runner.set_options(
        [], env={"PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"}
    )

    def assert_ics(build_file: str, expected: list[str]) -> None:
        rule_runner.write_files({"project/BUILD": build_file})
        lockfile_request = rule_runner.request(PythonLockfileRequest, [BlackLockfileSentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected)

    # If all code is Py38+, use those constraints. Otherwise, use subsystem constraints.
    assert_ics("python_library()", [global_constraint])
    assert_ics("python_library(interpreter_constraints=['==3.10.*'])", ["==3.10.*"])
    assert_ics(
        "python_library(interpreter_constraints=['==3.8.*', '==3.10.*'])", ["==3.8.*", "==3.10.*"]
    )

    assert_ics(
        "python_library(interpreter_constraints=['==3.6.*'])",
        Black.default_interpreter_constraints,
    )
    assert_ics(
        dedent(
            """\
            python_library(name='t1', interpreter_constraints=['==3.6.*'])
            python_library(name='t2', interpreter_constraints=['==3.8.*'])
            """
        ),
        Black.default_interpreter_constraints,
    )
    assert_ics(
        dedent(
            """\
            python_library(name='t1', interpreter_constraints=['==3.6.*', '>=3.8'])
            python_library(name='t2', interpreter_constraints=['==3.8.*'])
            """
        ),
        Black.default_interpreter_constraints,
    )

    # Ignore targets that are skipped.
    assert_ics(
        dedent(
            """\
            python_library(name='a', interpreter_constraints=['==3.6.*'], skip_black=True)
            python_library(name='b', interpreter_constraints=['==3.8.*'])
            """
        ),
        ["==3.8.*"],
    )
