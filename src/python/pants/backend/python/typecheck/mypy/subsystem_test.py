# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.backend.python.typecheck.mypy import subsystem
from pants.backend.python.typecheck.mypy.subsystem import MyPyConfigFile, MyPyFirstPartyPlugins
from pants.backend.python.util_rules import python_sources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules import config_files
from pants.engine.fs import EMPTY_DIGEST
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *subsystem.rules(),
            *config_files.rules(),
            *python_sources.rules(),
            QueryRule(MyPyConfigFile, []),
            QueryRule(MyPyFirstPartyPlugins, []),
        ],
        target_types=[PythonLibrary, PythonRequirementLibrary],
    )


def test_warn_if_python_version_configured(rule_runner: RuleRunner, caplog) -> None:
    config = {"mypy.ini": "[mypy]\npython_version = 3.6"}
    rule_runner.write_files(config)  # type: ignore[arg-type]
    config_digest = rule_runner.make_snapshot(config).digest

    def maybe_assert_configured(*, has_config: bool, args: list[str], warning: str = "") -> None:
        rule_runner.set_options(
            [f"--mypy-args={repr(args)}", f"--mypy-config-discovery={has_config}"]
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
            assert len(caplog.records) == 1
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
        warning=(
            "You set `python_version` in mypy.ini (which is used because of either config "
            "discovery or the `[mypy].config` option) and you set `--py2` in the `--mypy-args` "
            "option and you set `--python-version` in the `--mypy-args` option."
        ),
    )
    maybe_assert_configured(has_config=False, args=[])


def test_first_party_plugins(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement_library(name='mypy', requirements=['mypy==0.81'])
                python_requirement_library(name='colors', requirements=['ansicolors'])
                """
            ),
            "mypy-plugins/subdir1/util.py": "",
            "mypy-plugins/subdir1/BUILD": "python_library(dependencies=['mypy-plugins/subdir2'])",
            "mypy-plugins/subdir2/another_util.py": "",
            "mypy-plugins/subdir2/BUILD": "python_library()",
            "mypy-plugins/plugin.py": "",
            "mypy-plugins/BUILD": dedent(
                """\
                python_library(
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
        ]
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
