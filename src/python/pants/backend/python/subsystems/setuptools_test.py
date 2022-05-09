# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.python import target_types_rules
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems import setuptools
from pants.backend.python.subsystems.setuptools import SetuptoolsLockfileSentinel
from pants.backend.python.target_types import PythonDistribution, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_setup_lockfile_interpreter_constraints() -> None:
    rule_runner = RuleRunner(
        rules=[
            *setuptools.rules(),
            *target_types_rules.rules(),
            QueryRule(GeneratePythonLockfile, [SetuptoolsLockfileSentinel]),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonDistribution],
        objects={"python_artifact": PythonArtifact},
    )

    global_constraint = "==3.9.*"
    rule_runner.set_options(
        ["--setuptools-lockfile=lockfile.txt", "--no-python-infer-imports"],
        env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
    )

    def assert_ics(build_file: str, expected: list[str]) -> None:
        rule_runner.write_files({"project/BUILD": build_file, "project/f.py": ""})
        lockfile_request = rule_runner.request(
            GeneratePythonLockfile, [SetuptoolsLockfileSentinel()]
        )
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected)

    # If no dependencies for python_distribution, fall back to global [python] constraints.
    assert_ics("python_distribution(provides=setup_py(name='dist'))", [global_constraint])

    assert_ics(
        dedent(
            """\
            python_sources(name="lib")
            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=python_artifact(name="dist"),
            )
            """
        ),
        [global_constraint],
    )
    assert_ics(
        dedent(
            """\
            python_sources(name="lib", interpreter_constraints=["==2.7.*"])
            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=python_artifact(name="dist"),
            )
            """
        ),
        ["==2.7.*"],
    )
    assert_ics(
        dedent(
            """\
            python_sources(name="lib", interpreter_constraints=["==2.7.*", "==3.5.*"])
            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=python_artifact(name="dist"),
            )
            """
        ),
        ["==2.7.*", "==3.5.*"],
    )

    # If no python_distribution targets in repo, fall back to global [python] constraints.
    assert_ics("python_sources()", [global_constraint])

    # If there are multiple distinct ICs in the repo, we OR them. This is because setup_py.py will
    # build each Python distribution independently.
    assert_ics(
        dedent(
            """\
            python_sources(name="lib1", interpreter_constraints=["==2.7.*"])
            python_distribution(
                name="dist1",
                dependencies=[":lib1"],
                provides=python_artifact(name="dist"),
            )

            python_sources(name="lib2", interpreter_constraints=["==3.5.*"])
            python_distribution(
                name="dist2",
                dependencies=[":lib2"],
                provides=python_artifact(name="dist"),
            )
            """
        ),
        ["==2.7.*", "==3.5.*"],
    )
    assert_ics(
        dedent(
            """\
            python_sources(name="lib1", interpreter_constraints=["==2.7.*", "==3.5.*"])
            python_distribution(
                name="dist1",
                dependencies=[":lib1"],
                provides=python_artifact(name="dist"),
            )

            python_sources(name="lib2", interpreter_constraints=[">=3.5"])
            python_distribution(
                name="dist2",
                dependencies=[":lib2"],
                provides=python_artifact(name="dist"),
            )
            """
        ),
        ["==2.7.*", "==3.5.*", ">=3.5"],
    )
    assert_ics(
        dedent(
            """\
            python_sources(name="lib1")
            python_distribution(
                name="dist1",
                dependencies=[":lib1"],
                provides=python_artifact(name="dist"),
            )

            python_sources(name="lib2", interpreter_constraints=["==2.7.*"])
            python_distribution(
                name="dist2",
                dependencies=[":lib2"],
                provides=python_artifact(name="dist"),
            )

            python_sources(name="lib3", interpreter_constraints=[">=3.6"])
            python_distribution(
                name="dist3",
                dependencies=[":lib3"],
                provides=python_artifact(name="dist"),
            )
            """
        ),
        ["==2.7.*", global_constraint, ">=3.6"],
    )
