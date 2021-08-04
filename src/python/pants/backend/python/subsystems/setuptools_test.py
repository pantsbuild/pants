# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.experimental.python.lockfile import PythonLockfileRequest
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems import setuptools
from pants.backend.python.subsystems.setuptools import SetuptoolsLockfileSentinel
from pants.backend.python.target_types import PythonDistribution, PythonLibrary
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_setup_lockfile_interpreter_constraints() -> None:
    rule_runner = RuleRunner(
        rules=[
            *setuptools.rules(),
            QueryRule(PythonLockfileRequest, [SetuptoolsLockfileSentinel]),
        ],
        target_types=[PythonLibrary, PythonDistribution],
        objects={"setup_py": PythonArtifact},
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
        lockfile_request = rule_runner.request(
            PythonLockfileRequest, [SetuptoolsLockfileSentinel()]
        )
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected)

    # If no dependencies for python_distribution, fall back to global python-setup constraints.
    assert_ics("python_distribution(provides=setup_py(name='dist'))", [global_constraint])

    assert_ics(
        dedent(
            """\
            python_library(name="lib")
            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=setup_py(name="dist"),
            )
            """
        ),
        [global_constraint],
    )
    assert_ics(
        dedent(
            """\
            python_library(name="lib", interpreter_constraints=["==2.7.*"])
            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=setup_py(name="dist"),
            )
            """
        ),
        ["==2.7.*"],
    )
    assert_ics(
        dedent(
            """\
            python_library(name="lib", interpreter_constraints=["==2.7.*", "==3.5.*"])
            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=setup_py(name="dist"),
            )
            """
        ),
        ["==2.7.*", "==3.5.*"],
    )

    # If no python_distribution targets in repo, fall back to global python-setup constraints.
    assert_ics("python_library()", [global_constraint])

    # If there are multiple distinct ICs in the repo, we OR them. This is because setup_py.py will
    # build each Python distribution independently.
    assert_ics(
        dedent(
            """\
            python_library(name="lib1", interpreter_constraints=["==2.7.*"])
            python_distribution(
                name="dist1",
                dependencies=[":lib1"],
                provides=setup_py(name="dist"),
            )

            python_library(name="lib2", interpreter_constraints=["==3.5.*"])
            python_distribution(
                name="dist2",
                dependencies=[":lib2"],
                provides=setup_py(name="dist"),
            )
            """
        ),
        ["==2.7.*", "==3.5.*"],
    )
    assert_ics(
        dedent(
            """\
            python_library(name="lib1", interpreter_constraints=["==2.7.*", "==3.5.*"])
            python_distribution(
                name="dist1",
                dependencies=[":lib1"],
                provides=setup_py(name="dist"),
            )

            python_library(name="lib2", interpreter_constraints=[">=3.5"])
            python_distribution(
                name="dist2",
                dependencies=[":lib2"],
                provides=setup_py(name="dist"),
            )
            """
        ),
        ["==2.7.*", "==3.5.*", ">=3.5"],
    )
    assert_ics(
        dedent(
            """\
            python_library(name="lib1")
            python_distribution(
                name="dist1",
                dependencies=[":lib1"],
                provides=setup_py(name="dist"),
            )

            python_library(name="lib2", interpreter_constraints=["==2.7.*"])
            python_distribution(
                name="dist2",
                dependencies=[":lib2"],
                provides=setup_py(name="dist"),
            )

            python_library(name="lib3", interpreter_constraints=[">=3.6"])
            python_distribution(
                name="dist3",
                dependencies=[":lib3"],
                provides=setup_py(name="dist"),
            )
            """
        ),
        ["==2.7.*", global_constraint, ">=3.6"],
    )

    # If mixed interpreter constraints are disabled, simply look at the global ICs.
    assert_ics(
        dedent(
            """\
            python_library(name="lib", interpreter_constraints=["==2.7.*"])
            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=setup_py(name="dist"),
            )
            """
        ),
        [global_constraint],
        disable_mixed_ics=True,
    )
