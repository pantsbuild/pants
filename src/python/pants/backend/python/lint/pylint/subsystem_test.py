# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.pylint import skip_field
from pants.backend.python.lint.pylint.subsystem import PylintFirstPartyPlugins
from pants.backend.python.lint.pylint.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import python_sources
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
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
            QueryRule(PylintFirstPartyPlugins, []),
        ],
        target_types=[PythonSourcesGeneratorTarget, GenericTarget, PythonRequirementTarget],
    )


@skip_unless_all_pythons_present("3.8", "3.9")
def test_first_party_plugins(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(name='pylint', requirements=['pylint==2.11.1'])
                python_requirement(name='colors', requirements=['ansicolors'])
                """
            ),
            "pylint-plugins/subdir1/util.py": "",
            "pylint-plugins/subdir1/BUILD": dedent(
                """\
                python_sources(
                    interpreter_constraints=['==3.9.*'],
                    dependencies=['pylint-plugins/subdir2']
                )
                """
            ),
            "pylint-plugins/subdir2/another_util.py": "",
            "pylint-plugins/subdir2/BUILD": "python_sources(interpreter_constraints=['==3.8.*'])",
            "pylint-plugins/plugin.py": "",
            "pylint-plugins/BUILD": dedent(
                """\
                python_sources(
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
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    first_party_plugins = rule_runner.request(PylintFirstPartyPlugins, [])
    assert first_party_plugins.requirement_strings == FrozenOrderedSet(
        ["ansicolors", "pylint==2.11.1"]
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
                f"{PylintFirstPartyPlugins.PREFIX}/plugin.py": "",
                f"{PylintFirstPartyPlugins.PREFIX}/subdir1/util.py": "",
                f"{PylintFirstPartyPlugins.PREFIX}/subdir2/another_util.py": "",
            }
        ).digest
    )
