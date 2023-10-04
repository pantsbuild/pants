# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourcesGeneratorTarget
from pants.backend.python.typecheck.mypy import skip_field, subsystem
from pants.backend.python.typecheck.mypy.subsystem import MyPyConfigFile, MyPyFirstPartyPlugins
from pants.backend.python.util_rules import python_sources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.target_types import GenericTarget
from pants.core.util_rules import config_files
from pants.engine.fs import EMPTY_DIGEST
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *subsystem.rules(),
            *skip_field.rules(),
            *config_files.rules(),
            *python_sources.rules(),
            *target_types_rules.rules(),
            QueryRule(MyPyConfigFile, []),
            QueryRule(MyPyFirstPartyPlugins, []),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonRequirementTarget, GenericTarget],
    )


def test_warn_if_python_version_configured(rule_runner: PythonRuleRunner, caplog) -> None:
    config = {"mypy.ini": "[mypy]\npython_version = 3.6"}
    rule_runner.write_files(config)
    config_digest = rule_runner.make_snapshot(config).digest

    def maybe_assert_configured(*, has_config: bool, args: list[str], warning: str = "") -> None:
        rule_runner.set_options(
            [f"--mypy-args={repr(args)}", f"--mypy-config-discovery={has_config}"],
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )
        result = rule_runner.request(MyPyConfigFile, [])

        assert result.digest == (config_digest if has_config else EMPTY_DIGEST)
        should_be_configured = has_config or bool(args)
        assert result._python_version_configured == should_be_configured

        autoset_python_version = result.python_version_to_autoset(
            InterpreterConstraints([">=3.6"]), ["2.7", "3.6", "3.7", "3.8"]
        )
        if should_be_configured:
            assert autoset_python_version is None
        else:
            assert autoset_python_version == "3.6"

        if should_be_configured:
            assert caplog.records
            assert warning in caplog.text
            caplog.clear()
        else:
            assert not caplog.records

    maybe_assert_configured(
        has_config=True, args=[], warning="You set `python_version` in mypy.ini"
    )
    maybe_assert_configured(
        has_config=False, args=["--py2"], warning="You set `--py2` in the `--mypy-args` option"
    )
    maybe_assert_configured(
        has_config=False,
        args=["--python-version=3.6"],
        warning="You set `--python-version` in the `--mypy-args` option",
    )
    maybe_assert_configured(
        has_config=True,
        args=["--py2", "--python-version=3.6"],
        warning=softwrap(
            """
            You set `python_version` in mypy.ini (which is used because of either config
            discovery or the `[mypy].config` option) and you set `--py2` in the `--mypy-args`
            option and you set `--python-version` in the `--mypy-args` option.
            """
        ),
    )
    maybe_assert_configured(has_config=False, args=[])


def test_first_party_plugins(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(name='mypy', requirements=['mypy==0.81'])
                python_requirement(name='colors', requirements=['ansicolors'])
                """
            ),
            "mypy-plugins/subdir1/util.py": "",
            "mypy-plugins/subdir1/BUILD": "python_sources(dependencies=['mypy-plugins/subdir2'])",
            "mypy-plugins/subdir2/another_util.py": "",
            "mypy-plugins/subdir2/BUILD": "python_sources()",
            "mypy-plugins/plugin.py": "",
            "mypy-plugins/BUILD": dedent(
                """\
                python_sources(
                    dependencies=['//:mypy', '//:colors', "mypy-plugins/subdir1"]
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--source-root-patterns=mypy-plugins",
            "--mypy-source-plugins=mypy-plugins/plugin.py",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    first_party_plugins = rule_runner.request(MyPyFirstPartyPlugins, [])
    assert first_party_plugins.requirement_strings == FrozenOrderedSet(["ansicolors", "mypy==0.81"])
    assert (
        first_party_plugins.sources_digest
        == rule_runner.make_snapshot(
            {
                "mypy-plugins/plugin.py": "",
                "mypy-plugins/subdir1/util.py": "",
                "mypy-plugins/subdir2/another_util.py": "",
            }
        ).digest
    )
    assert first_party_plugins.source_roots == ("mypy-plugins",)
