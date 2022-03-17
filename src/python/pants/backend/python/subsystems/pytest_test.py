# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.pytest import PyTest, PytestLockfileSentinel
from pants.backend.python.subsystems.pytest import rules as subsystem_rules
from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonTestsGeneratorTarget,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.target_types import GenericTarget
from pants.option.ranked_value import Rank, RankedValue
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_setup_lockfile_interpreter_constraints() -> None:
    rule_runner = RuleRunner(
        rules=[
            *subsystem_rules(),
            *target_types_rules.rules(),
            QueryRule(GeneratePythonLockfile, [PytestLockfileSentinel]),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonTestsGeneratorTarget, GenericTarget],
    )

    global_constraint = "==3.9.*"
    rule_runner.set_options(
        ["--pytest-lockfile=lockfile.txt", "--no-python-infer-imports"],
        env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
    )

    def assert_ics(build_file: str, expected: list[str]) -> None:
        rule_runner.write_files(
            {"project/BUILD": build_file, "project/f.py": "", "project/f_test.py": ""}
        )
        lockfile_request = rule_runner.request(GeneratePythonLockfile, [PytestLockfileSentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected)

    assert_ics("python_tests()", [global_constraint])
    assert_ics("python_tests(interpreter_constraints=['==2.7.*'])", ["==2.7.*"])
    assert_ics(
        "python_tests(interpreter_constraints=['==2.7.*', '==3.8.*'])", ["==2.7.*", "==3.8.*"]
    )

    # If no Python targets in repo, fall back to global [python] constraints.
    assert_ics("target()", [global_constraint])

    # Only care about `python_tests` and their transitive deps, not unused `python_sources`s.
    assert_ics("python_sources(interpreter_constraints=['==2.7.*'])", [global_constraint])

    # Ignore targets that are skipped.
    assert_ics(
        dedent(
            """\
            python_tests(name='a', interpreter_constraints=['==2.7.*'])
            python_tests(name='b', interpreter_constraints=['==3.8.*'], skip_tests=True)
            """
        ),
        ["==2.7.*"],
    )

    # If there are multiple distinct ICs in the repo, we OR them because the lockfile needs to be
    # compatible with every target.
    assert_ics(
        dedent(
            """\
            python_tests(name='a', interpreter_constraints=['==2.7.*'])
            python_tests(name='b', interpreter_constraints=['==3.8.*'])
            """
        ),
        ["==2.7.*", "==3.8.*"],
    )
    assert_ics(
        dedent(
            """\
            python_tests(name='a', interpreter_constraints=['==2.7.*', '==3.8.*'])
            python_tests(name='b', interpreter_constraints=['>=3.8'])
            """
        ),
        ["==2.7.*", "==3.8.*", ">=3.8"],
    )
    assert_ics(
        dedent(
            """\
            python_tests(name='a')
            python_tests(name='b', interpreter_constraints=['==2.7.*'])
            python_tests(name='c', interpreter_constraints=['>=3.6'])
            """
        ),
        ["==2.7.*", global_constraint, ">=3.6"],
    )

    # Also consider transitive deps. They should be ANDed within each python_tests's transitive
    # closure like normal, but then ORed across each python_tests closure.
    assert_ics(
        dedent(
            """\
            python_sources(name='lib', interpreter_constraints=['==2.7.*', '==3.6.*'])
            python_tests(name='tests', dependencies=[":lib"], interpreter_constraints=['==2.7.*'])
            """
        ),
        ["==2.7.*", "==2.7.*,==3.6.*"],
    )
    assert_ics(
        dedent(
            """\
            python_sources(name='lib1', interpreter_constraints=['==2.7.*', '==3.6.*'])
            python_tests(name='tests1', dependencies=[":lib1"], interpreter_constraints=['==2.7.*'])

            python_sources(name='lib2', interpreter_constraints=['>=3.7'])
            python_tests(name='tests2', dependencies=[":lib2"], interpreter_constraints=['==3.8.*'])
            """
        ),
        ["==2.7.*", "==2.7.*,==3.6.*", ">=3.7,==3.8.*"],
    )


def test_validate_pytest_cov_included() -> None:
    def validate(extra_requirements: list[str] | None = None) -> None:
        extra_reqs_rv = (
            RankedValue(Rank.CONFIG, extra_requirements)
            if extra_requirements is not None
            else RankedValue(Rank.HARDCODED, PyTest.default_extra_requirements)
        )
        pytest = create_subsystem(PyTest, extra_requirements=extra_reqs_rv)
        pytest.validate_pytest_cov_included()

    # Default should not error.
    validate()
    # Canonicalize project name.
    validate(["PyTeST_cOV"])

    with pytest.raises(ValueError) as exc:
        validate([])
    assert "missing `pytest-cov`" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate(["custom-plugin"])
    assert "missing `pytest-cov`" in str(exc.value)
