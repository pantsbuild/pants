# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.ruff import skip_field
from pants.backend.python.lint.ruff.subsystem import Ruff, RuffLockfileSentinel
from pants.backend.python.lint.ruff.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import python_sources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.target_types import GenericTarget
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *subsystem_rules(),
            *skip_field.rules(),
            *python_sources.rules(),
            *target_types_rules.rules(),
            QueryRule(GeneratePythonLockfile, [RuffLockfileSentinel]),
        ],
        target_types=[PythonSourcesGeneratorTarget, GenericTarget, PythonRequirementTarget],
    )


def test_setup_lockfile(rule_runner) -> None:
    global_constraint = "CPython<4,>=3.7"

    def assert_lockfile_request(
        build_file: str,
        expected_ics: list[str],
        *,
        extra_expected_requirements: list[str] | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        rule_runner.write_files({"project/BUILD": build_file, "project/f.py": ""})
        rule_runner.set_options(
            ["--ruff-lockfile=lockfile.txt", *(extra_args or [])],
            env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )
        lockfile_request = rule_runner.request(GeneratePythonLockfile, [RuffLockfileSentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected_ics)
        assert lockfile_request.requirements == FrozenOrderedSet(
            [
                Ruff.default_version,
                *Ruff.default_extra_requirements,
                *(extra_expected_requirements or ()),
            ]
        )

    assert_lockfile_request("python_sources()", [global_constraint])
    assert_lockfile_request(
        "python_sources(interpreter_constraints=['CPython<4,>=3.7'])", ["CPython<4,>=3.7"]
    )

    # If no Python targets in repo, fall back to global [python] constraints.
    assert_lockfile_request("target()", [global_constraint])

    # Ignore targets that are skipped.
    assert_lockfile_request(
        dedent(
            """\
            python_sources(name='a', interpreter_constraints=['CPython<4,>=3.7'])
            python_sources(name='b', interpreter_constraints=['CPython<4,>=3.7'], skip_ruff=True)
            """
        ),
        ["CPython<4,>=3.7"],
    )
