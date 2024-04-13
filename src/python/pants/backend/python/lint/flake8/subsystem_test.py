# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.flake8 import skip_field
from pants.backend.python.lint.flake8.subsystem import Flake8FirstPartyPlugins
from pants.backend.python.lint.flake8.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import python_sources
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
