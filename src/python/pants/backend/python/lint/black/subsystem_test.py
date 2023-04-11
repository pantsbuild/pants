# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

from pants.backend.python import target_types_rules
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.black import skip_field
from pants.backend.python.lint.black.subsystem import Black, BlackLockfileSentinel
from pants.backend.python.lint.black.subsystem import rules as subsystem_rules
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
            QueryRule(GeneratePythonLockfile, [BlackLockfileSentinel]),
        ],
        target_types=[PythonSourcesGeneratorTarget, GenericTarget],
    )

    global_constraint = "==3.9.*"
    rule_runner.set_options(
        ["--black-lockfile=lockfile.txt", "--no-python-infer-imports"],
        env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
    )

    def assert_ics(build_file: str, expected: Iterable[str]) -> None:
        rule_runner.write_files({"project/BUILD": build_file, "project/f.py": ""})
        lockfile_request = rule_runner.request(GeneratePythonLockfile, [BlackLockfileSentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected)

    # If all code is Py38+, use those constraints. Otherwise, use subsystem constraints.
    assert_ics("python_sources()", [global_constraint])
    assert_ics("python_sources(interpreter_constraints=['==3.10.*'])", ["==3.10.*"])
    assert_ics(
        "python_sources(interpreter_constraints=['==3.8.*', '==3.10.*'])", ["==3.8.*", "==3.10.*"]
    )

    assert_ics(
        "python_sources(interpreter_constraints=['==3.6.*'])",
        Black.default_interpreter_constraints,
    )
    assert_ics(
        dedent(
            """\
            python_sources(name='t1', interpreter_constraints=['==3.6.*'])
            python_sources(name='t2', interpreter_constraints=['==3.8.*'])
            """
        ),
        Black.default_interpreter_constraints,
    )
    assert_ics(
        dedent(
            """\
            python_sources(name='t1', interpreter_constraints=['==3.6.*', '>=3.8'])
            python_sources(name='t2', interpreter_constraints=['==3.8.*'])
            """
        ),
        Black.default_interpreter_constraints,
    )

    # Ignore targets that are skipped.
    assert_ics(
        dedent(
            """\
            python_sources(name='a', interpreter_constraints=['==3.6.*'], skip_black=True)
            python_sources(name='b', interpreter_constraints=['==3.8.*'])
            """
        ),
        ["==3.8.*"],
    )
