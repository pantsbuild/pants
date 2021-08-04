# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.experimental.python.lockfile import PythonLockfileRequest
from pants.backend.python.lint.bandit import skip_field
from pants.backend.python.lint.bandit.subsystem import BanditLockfileSentinel
from pants.backend.python.lint.bandit.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import PythonLibrary
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.target_types import GenericTarget
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_setup_lockfile_interpreter_constraints() -> None:
    rule_runner = RuleRunner(
        rules=[
            *subsystem_rules(),
            *skip_field.rules(),
            QueryRule(PythonLockfileRequest, [BanditLockfileSentinel]),
        ],
        target_types=[PythonLibrary, GenericTarget],
    )

    global_constraint = "==3.9.*"

    def assert_ics(
        build_file: str, expected: list[str], *, disable_mixed_ics: bool = False
    ) -> None:
        rule_runner.set_options(
            [f"--python-setup-disable-mixed-interpreter-constraints={disable_mixed_ics}"],
            env={"PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
        )
        rule_runner.write_files({"project/BUILD": build_file})
        lockfile_request = rule_runner.request(PythonLockfileRequest, [BanditLockfileSentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected)

    assert_ics("python_library()", [global_constraint])
    assert_ics("python_library(interpreter_constraints=['==2.7.*'])", ["==2.7.*"])
    assert_ics(
        "python_library(interpreter_constraints=['==2.7.*', '==3.5.*'])", ["==2.7.*", "==3.5.*"]
    )

    # If no Python targets in repo, fall back to global python-setup constraints.
    assert_ics("target()", [global_constraint])

    # Ignore targets that are skipped.
    assert_ics(
        dedent(
            """\
            python_library(name='a', interpreter_constraints=['==2.7.*'])
            python_library(name='b', interpreter_constraints=['==3.5.*'], skip_bandit=True)
            """
        ),
        ["==2.7.*"],
    )

    # If there are multiple distinct ICs in the repo, we OR them. This is because Flake8 will
    # group into each distinct IC.
    assert_ics(
        dedent(
            """\
            python_library(name='a', interpreter_constraints=['==2.7.*'])
            python_library(name='b', interpreter_constraints=['==3.5.*'])
            """
        ),
        ["==2.7.*", "==3.5.*"],
    )
    assert_ics(
        dedent(
            """\
            python_library(name='a', interpreter_constraints=['==2.7.*', '==3.5.*'])
            python_library(name='b', interpreter_constraints=['>=3.5'])
            """
        ),
        ["==2.7.*", "==3.5.*", ">=3.5"],
    )
    assert_ics(
        dedent(
            """\
            python_library(name='a')
            python_library(name='b', interpreter_constraints=['==2.7.*'])
            python_library(name='c', interpreter_constraints=['>=3.6'])
            """
        ),
        ["==2.7.*", global_constraint, ">=3.6"],
    )

    # If mixed interpreter constraints are disabled, simply look at the global ICs.
    assert_ics(
        "python_library(interpreter_constraints=['==2.7.*'])",
        [global_constraint],
        disable_mixed_ics=True,
    )
