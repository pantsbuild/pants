# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.flake8 import skip_field
from pants.backend.python.lint.flake8.subsystem import (
    Flake8,
    Flake8FirstPartyPlugins,
    Flake8LockfileSentinel,
)
from pants.backend.python.lint.flake8.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import python_sources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.build_graph.address import Address
from pants.core.target_types import GenericTarget
from pants.testutil.python_interpreter_selection import skip_unless_all_pythons_present
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *subsystem_rules(),
            *skip_field.rules(),
            *python_sources.rules(),
            *target_types_rules.rules(),
            QueryRule(Flake8FirstPartyPlugins, []),
            QueryRule(GeneratePythonLockfile, [Flake8LockfileSentinel]),
        ],
        target_types=[PythonSourcesGeneratorTarget, GenericTarget, PythonRequirementTarget],
    )


@skip_unless_all_pythons_present("3.8", "3.9")
def test_first_party_plugins(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(name='flake8', requirements=['flake8==2.11.1'])
                python_requirement(name='colors', requirements=['ansicolors'])
                """
            ),
            "flake8-plugins/subdir1/util.py": "",
            "flake8-plugins/subdir1/BUILD": dedent(
                """\
                python_sources(
                    interpreter_constraints=['==3.9.*'],
                    dependencies=['flake8-plugins/subdir2']
                )
                """
            ),
            "flake8-plugins/subdir2/another_util.py": "",
            "flake8-plugins/subdir2/BUILD": "python_sources(interpreter_constraints=['==3.8.*'])",
            "flake8-plugins/plugin.py": "",
            "flake8-plugins/BUILD": dedent(
                """\
                python_sources(
                    dependencies=['//:flake8', '//:colors', "flake8-plugins/subdir1"]
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--source-root-patterns=flake8-plugins",
            "--flake8-source-plugins=flake8-plugins/plugin.py",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    first_party_plugins = rule_runner.request(Flake8FirstPartyPlugins, [])
    assert first_party_plugins.requirement_strings == FrozenOrderedSet(
        ["ansicolors", "flake8==2.11.1"]
    )
    assert first_party_plugins.interpreter_constraints_fields == FrozenOrderedSet(
        [
            InterpreterConstraintsField(ic, Address("", target_name="tgt"))
            for ic in (None, ["==3.9.*"], ["==3.8.*"])
        ]
    )
    assert (
        first_party_plugins.sources_digest
        == rule_runner.make_snapshot(
            {
                f"{Flake8FirstPartyPlugins.PREFIX}/plugin.py": "",
                f"{Flake8FirstPartyPlugins.PREFIX}/subdir1/util.py": "",
                f"{Flake8FirstPartyPlugins.PREFIX}/subdir2/another_util.py": "",
            }
        ).digest
    )


def test_setup_lockfile(rule_runner) -> None:
    global_constraint = "==3.9.*"

    def assert_lockfile_request(
        build_file: str,
        expected_ics: list[str],
        *,
        extra_expected_requirements: list[str] | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        rule_runner.write_files({"project/BUILD": build_file, "project/f.py": ""})
        rule_runner.set_options(
            ["--flake8-lockfile=lockfile.txt", *(extra_args or [])],
            env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )
        lockfile_request = rule_runner.request(GeneratePythonLockfile, [Flake8LockfileSentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected_ics)
        assert lockfile_request.requirements == FrozenOrderedSet(
            [
                Flake8.default_version,
                *Flake8.default_extra_requirements,
                *(extra_expected_requirements or ()),
            ]
        )

    assert_lockfile_request("python_sources()", [global_constraint])
    assert_lockfile_request("python_sources(interpreter_constraints=['==2.7.*'])", ["==2.7.*"])
    assert_lockfile_request(
        "python_sources(interpreter_constraints=['==2.7.*', '==3.5.*'])", ["==2.7.*", "==3.5.*"]
    )

    # If no Python targets in repo, fall back to global [python] constraints.
    assert_lockfile_request("target()", [global_constraint])

    # Ignore targets that are skipped.
    assert_lockfile_request(
        dedent(
            """\
            python_sources(name='a', interpreter_constraints=['==2.7.*'])
            python_sources(name='b', interpreter_constraints=['==3.5.*'], skip_flake8=True)
            """
        ),
        ["==2.7.*"],
    )

    # If there are multiple distinct ICs in the repo, we OR them. This is because Flake8 will
    # group into each distinct IC.
    assert_lockfile_request(
        dedent(
            """\
            python_sources(name='a', interpreter_constraints=['==2.7.*'])
            python_sources(name='b', interpreter_constraints=['==3.5.*'])
            """
        ),
        ["==2.7.*", "==3.5.*"],
    )
    assert_lockfile_request(
        dedent(
            """\
            python_sources(name='a', interpreter_constraints=['==2.7.*', '==3.5.*'])
            python_sources(name='b', interpreter_constraints=['>=3.5'])
            """
        ),
        ["==2.7.*", "==3.5.*", ">=3.5"],
    )
    assert_lockfile_request(
        dedent(
            """\
            python_sources(name='a')
            python_sources(name='b', interpreter_constraints=['==2.7.*'])
            python_sources(name='c', interpreter_constraints=['>=3.6'])
            """
        ),
        ["==2.7.*", global_constraint, ">=3.6"],
    )

    # Check that source_plugins are included, even if they aren't linted directly. Plugins
    # consider transitive deps.
    assert_lockfile_request(
        dedent(
            """\
            python_sources(
                name="lib",
                interpreter_constraints=['==3.8.*'],
            )
            python_sources(
                name="plugin",
                interpreter_constraints=['==2.7.*'],
                skip_flake8=True,
            )
            """
        ),
        ["==2.7.*,==3.8.*"],
        extra_args=["--flake8-source-plugins=project:plugin"],
    )
    assert_lockfile_request(
        dedent(
            """\
            python_sources(
                dependencies=[":direct_dep"],
                interpreter_constraints=['==3.8.*'],
                skip_flake8=True,
            )
            python_sources(
                name="direct_dep",
                dependencies=[":transitive_dep"],
                interpreter_constraints=['==3.8.*'],
                skip_flake8=True,
            )
            python_sources(
                name="transitive_dep",
                dependencies=[":thirdparty"],
                interpreter_constraints=['==2.7.*', '==3.8.*'],
                skip_flake8=True,
            )
            python_requirement(name="thirdparty", requirements=["ansicolors"])
            """
        ),
        ["==2.7.*,==3.8.*", "==3.8.*"],
        extra_args=["--flake8-source-plugins=project"],
        extra_expected_requirements=["ansicolors"],
    )
