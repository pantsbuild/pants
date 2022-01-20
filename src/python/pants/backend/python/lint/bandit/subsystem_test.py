# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.python import target_types_rules
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.bandit import skip_field
from pants.backend.python.lint.bandit.subsystem import BanditLockfileSentinel
from pants.backend.python.lint.bandit.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.target_types import GenericTarget
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_setup_lockfile_interpreter_constraints() -> None:
    rule_runner = RuleRunner(
        rules=[
            *subsystem_rules(),
            *skip_field.rules(),
            *target_types_rules.rules(),
            QueryRule(GeneratePythonLockfile, [BanditLockfileSentinel]),
        ],
        target_types=[PythonSourcesGeneratorTarget, GenericTarget],
    )

    global_constraint = "==3.9.*"
    rule_runner.set_options(
        ["--bandit-lockfile=lockfile.txt"],
        env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
    )

    def assert_ics(build_file: str, expected: list[str]) -> None:
        rule_runner.write_files({"project/BUILD": build_file, "project/f.py": ""})
        lockfile_request = rule_runner.request(GeneratePythonLockfile, [BanditLockfileSentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected)

    assert_ics("python_sources()", [global_constraint])
    assert_ics("python_sources(interpreter_constraints=['==2.7.*'])", ["==2.7.*"])
    assert_ics(
        "python_sources(interpreter_constraints=['==2.7.*', '==3.5.*'])", ["==2.7.*", "==3.5.*"]
    )

    # If no Python targets in repo, fall back to global [python] constraints.
    assert_ics("target()", [global_constraint])

    # Ignore targets that are skipped.
    assert_ics(
        dedent(
            """\
            python_sources(name='a', interpreter_constraints=['==2.7.*'])
            python_sources(name='b', interpreter_constraints=['==3.5.*'], skip_bandit=True)
            """
        ),
        ["==2.7.*"],
    )

    # If there are multiple distinct ICs in the repo, we OR them. This is because Flake8 will
    # group into each distinct IC.
    assert_ics(
        dedent(
            """\
            python_sources(name='a', interpreter_constraints=['==2.7.*'])
            python_sources(name='b', interpreter_constraints=['==3.5.*'])
            """
        ),
        ["==2.7.*", "==3.5.*"],
    )
    assert_ics(
        dedent(
            """\
            python_sources(name='a', interpreter_constraints=['==2.7.*', '==3.5.*'])
            python_sources(name='b', interpreter_constraints=['>=3.5'])
            """
        ),
        ["==2.7.*", "==3.5.*", ">=3.5"],
    )
    assert_ics(
        dedent(
            """\
            python_sources(name='a')
            python_sources(name='b', interpreter_constraints=['==2.7.*'])
            python_sources(name='c', interpreter_constraints=['>=3.6'])
            """
        ),
        ["==2.7.*", global_constraint, ">=3.6"],
    )
