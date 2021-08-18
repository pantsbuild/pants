# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.experimental.python.lockfile import PythonLockfileRequest
from pants.backend.python.lint.pylint import skip_field
from pants.backend.python.lint.pylint.subsystem import (
    Pylint,
    PylintFirstPartyPlugins,
    PylintLockfileSentinel,
)
from pants.backend.python.lint.pylint.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonLibrary,
    PythonRequirementLibrary,
)
from pants.backend.python.util_rules import python_sources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *subsystem_rules(),
            *skip_field.rules(),
            *python_sources.rules(),
            QueryRule(PylintFirstPartyPlugins, []),
            QueryRule(PythonLockfileRequest, [PylintLockfileSentinel]),
        ],
        target_types=[PythonLibrary, GenericTarget, PythonRequirementLibrary],
    )


def test_first_party_plugins(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement_library(name='pylint', requirements=['pylint==2.6.2'])
                python_requirement_library(name='colors', requirements=['ansicolors'])
                """
            ),
            "pylint-plugins/subdir1/util.py": "",
            "pylint-plugins/subdir1/BUILD": dedent(
                """\
                python_library(
                    interpreter_constraints=['==3.5.*'],
                    dependencies=['pylint-plugins/subdir2']
                )
                """
            ),
            "pylint-plugins/subdir2/another_util.py": "",
            "pylint-plugins/subdir2/BUILD": ("python_library(interpreter_constraints=['==3.4.*'])"),
            "pylint-plugins/plugin.py": "",
            "pylint-plugins/BUILD": dedent(
                """\
                python_library(
                    dependencies=['//:pylint', '//:colors', "pylint-plugins/subdir1"]
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--source-root-patterns=pylint-plugins",
            "--pylint-source-plugins=pylint-plugins/plugin.py",
        ]
    )
    first_party_plugins = rule_runner.request(PylintFirstPartyPlugins, [])
    assert first_party_plugins.requirement_strings == FrozenOrderedSet(
        ["ansicolors", "pylint==2.6.2"]
    )
    assert first_party_plugins.interpreter_constraints_fields == FrozenOrderedSet(
        [
            InterpreterConstraintsField(ic, Address("", target_name="tgt"))
            for ic in (None, ["==3.5.*"], ["==3.4.*"])
        ]
    )
    assert (
        first_party_plugins.sources_digest
        == rule_runner.make_snapshot(
            {
                f"{PylintFirstPartyPlugins.PREFIX}/plugin.py": "",
                f"{PylintFirstPartyPlugins.PREFIX}/subdir1/util.py": "",
                f"{PylintFirstPartyPlugins.PREFIX}/subdir2/another_util.py": "",
            }
        ).digest
    )


def test_setup_lockfile_interpreter_constraints(rule_runner: RuleRunner) -> None:
    global_constraint = "==3.9.*"

    def assert_lockfile_requst(
        build_file: str,
        expected_ics: list[str],
        *,
        extra_expected_requirements: list[str] | None = None,
        args: list[str] | None = None,
    ) -> None:
        rule_runner.write_files({"project/BUILD": build_file})
        rule_runner.set_options(
            args or [],
            env={"PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
        )
        lockfile_request = rule_runner.request(PythonLockfileRequest, [PylintLockfileSentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected_ics)
        assert lockfile_request.requirements == FrozenOrderedSet(
            [
                Pylint.default_version,
                *Pylint.default_extra_requirements,
                *(extra_expected_requirements or ()),
            ]
        )

    assert_lockfile_requst("python_library()", [global_constraint])
    assert_lockfile_requst("python_library(interpreter_constraints=['==2.7.*'])", ["==2.7.*"])
    assert_lockfile_requst(
        "python_library(interpreter_constraints=['==2.7.*', '==3.5.*'])", ["==2.7.*", "==3.5.*"]
    )

    # If no Python targets in repo, fall back to global python-setup constraints.
    assert_lockfile_requst("target()", [global_constraint])

    # Ignore targets that are skipped.
    assert_lockfile_requst(
        dedent(
            """\
            python_library(name='a', interpreter_constraints=['==2.7.*'])
            python_library(name='b', interpreter_constraints=['==3.5.*'], skip_pylint=True)
            """
        ),
        ["==2.7.*"],
    )

    # If there are multiple distinct ICs in the repo, we OR them because the lockfile needs to be
    # compatible with every target.
    assert_lockfile_requst(
        dedent(
            """\
            python_library(name='a', interpreter_constraints=['==2.7.*'])
            python_library(name='b', interpreter_constraints=['==3.5.*'])
            """
        ),
        ["==2.7.*", "==3.5.*"],
    )
    assert_lockfile_requst(
        dedent(
            """\
            python_library(name='a', interpreter_constraints=['==2.7.*', '==3.5.*'])
            python_library(name='b', interpreter_constraints=['>=3.5'])
            """
        ),
        ["==2.7.*", "==3.5.*", ">=3.5"],
    )
    assert_lockfile_requst(
        dedent(
            """\
            python_library(name='a')
            python_library(name='b', interpreter_constraints=['==2.7.*'])
            python_library(name='c', interpreter_constraints=['>=3.6'])
            """
        ),
        ["==2.7.*", global_constraint, ">=3.6"],
    )

    # Also consider direct deps (but not transitive). They should be ANDed within each target's
    # closure like normal, but then ORed across each closure.
    assert_lockfile_requst(
        dedent(
            """\
            python_library(
                name='transitive_dep', interpreter_constraints=['==99'], skip_pylint=True,
            )
            python_library(
                name='dep',
                dependencies=[":transitive_dep"],
                interpreter_constraints=['==2.7.*', '==3.6.*'],
                skip_pylint=True,
            )
            python_library(name='app', dependencies=[":dep"], interpreter_constraints=['==2.7.*'])
            """
        ),
        ["==2.7.*", "==2.7.*,==3.6.*"],
    )
    assert_lockfile_requst(
        dedent(
            """\
            python_library(
                name='lib1', interpreter_constraints=['==2.7.*', '==3.6.*'], skip_pylint=True
            )
            python_library(name='app1', dependencies=[":lib1"], interpreter_constraints=['==2.7.*'])

            python_library(
                name='lib2', interpreter_constraints=['>=3.7'], skip_pylint=True
            )
            python_library(name='app2', dependencies=[":lib2"], interpreter_constraints=['==3.8.*'])
            """
        ),
        ["==2.7.*", "==2.7.*,==3.6.*", ">=3.7,==3.8.*"],
    )

    # Check that source_plugins are included, even if they aren't linted directly. Plugins
    # consider transitive deps.
    assert_lockfile_requst(
        dedent(
            """\
            python_library(
                name="lib",
                sources=[],
                interpreter_constraints=['==3.6.*'],
            )
            python_library(
                name="plugin",
                sources=[],
                interpreter_constraints=['==2.7.*'],
                skip_pylint=True,
            )
            """
        ),
        ["==2.7.*,==3.6.*"],
        args=["--pylint-source-plugins=project:plugin"],
    )
    assert_lockfile_requst(
        dedent(
            """\
            python_library(
                sources=[],
                dependencies=[":direct_dep"],
                interpreter_constraints=['==3.6.*'],
                skip_pylint=True,
            )
            python_library(
                name="direct_dep",
                sources=[],
                dependencies=[":transitive_dep"],
                interpreter_constraints=['==3.6.*'],
                skip_pylint=True,
            )
            python_library(
                name="transitive_dep",
                sources=[],
                dependencies=[":thirdparty"],
                interpreter_constraints=['==2.7.*', '==3.6.*'],
                skip_pylint=True,
            )
            python_requirement_library(name="thirdparty", requirements=["ansicolors"])
            """
        ),
        ["==2.7.*,==3.6.*", "==3.6.*"],
        args=["--pylint-source-plugins=project"],
        extra_expected_requirements=["ansicolors"],
    )
