# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.python import target_types_rules
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonSourceField, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.partition import _find_all_unique_interpreter_constraints
from pants.core.target_types import GenericTarget
from pants.engine.rules import QueryRule, SubsystemRule, rule
from pants.engine.target import FieldSet, Target
from pants.testutil.rule_runner import RuleRunner


def test_find_unique_interpreter_constraints() -> None:
    class AnotherMockFieldSet(FieldSet):
        required_fields = (PythonSourceField,)

        @classmethod
        def opt_out(cls, tgt: Target) -> bool:
            return tgt.address.target_name == "skip_me"

    @rule
    async def run_rule(python_setup: PythonSetup) -> InterpreterConstraints:
        return await _find_all_unique_interpreter_constraints(python_setup, AnotherMockFieldSet)

    rule_runner = RuleRunner(
        rules=[
            run_rule,
            *target_types_rules.rules(),
            SubsystemRule(PythonSetup),
            QueryRule(InterpreterConstraints, []),
        ],
        target_types=[PythonSourcesGeneratorTarget, GenericTarget],
    )

    global_constraint = "==3.9.*"
    rule_runner.set_options(
        [],
        env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
    )

    def assert_ics(build_file: str, expected: list[str]) -> None:
        rule_runner.write_files({"project/BUILD": build_file, "project/f.py": ""})
        result = rule_runner.request(InterpreterConstraints, [])
        assert result == InterpreterConstraints(expected)

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
            python_sources(name='skip_me', interpreter_constraints=['==3.5.*'])
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
