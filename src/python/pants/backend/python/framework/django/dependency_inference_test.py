# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.dependency_inference import parse_python_dependencies
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonDependencies,
)
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonImportInfo as ImpInfo,
)
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsePythonDependenciesRequest,
)
from pants.backend.python.framework.django import dependency_inference, detect_apps
from pants.backend.python.target_types import PythonSourceField, PythonSourceTarget
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.testutil.python_interpreter_selection import (
    skip_unless_python27_present,
    skip_unless_python37_present,
    skip_unless_python38_present,
    skip_unless_python39_present,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.strutil import softwrap


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *parse_python_dependencies.rules(),
            *stripped_source_files.rules(),
            *pex.rules(),
            *dependency_inference.rules(),
            *detect_apps.rules(),
            QueryRule(ParsedPythonDependencies, [ParsePythonDependenciesRequest]),
        ],
        target_types=[PythonSourceTarget],
    )


def assert_deps_parsed(
    rule_runner: RuleRunner,
    content: str,
    *,
    constraints: str,
    expected_imports: dict[str, ImpInfo] | None = None,
    expected_assets: list[str] | None = None,
    filename: str = "path/to/app0/migrations/0001_initial.py",
) -> None:
    expected_imports = expected_imports or {}
    expected_assets = expected_assets or []
    rule_runner.set_options(
        [
            "--no-python-infer-string-imports",
            "--no-python-infer-assets",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    rule_runner.write_files(
        {
            "BUILD": f"python_source(name='t', source={repr(filename)})",
            "path/to/app1/BUILD": softwrap(
                f"""\
                python_source(
                  source="apps.py",
                  interpreter_constraints=['{constraints}'],
                )
                """
            ),
            "path/to/app1/apps.py": softwrap(
                """\
                class App1AppConfig(AppConfig):
                    name = "path.to.app1"
                    label = "app1"
                """
            ),
            "another/path/app2/BUILD": softwrap(
                f"""\
                python_source(
                  source="apps.py",
                  interpreter_constraints=['{constraints}'],
                )
                """
            ),
            "another/path/app2/apps.py": softwrap(
                """\
                class App2AppConfig(AppConfig):
                    name = "another.path.app2"
                    label = "app2_label"
                """
            ),
            filename: content,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t"))
    result = rule_runner.request(
        ParsedPythonDependencies,
        [
            ParsePythonDependenciesRequest(
                tgt[PythonSourceField],
                InterpreterConstraints([constraints]),
            )
        ],
    )
    assert dict(result.imports) == expected_imports
    assert list(result.assets) == sorted(expected_assets)


def do_test_migration_dependencies(rule_runner: RuleRunner, constraints: str) -> None:
    content = dedent(
        """\
        class Migration(migrations.Migration):
            dependencies = [
              ("app1", "0012_some_migration"),
              ("app2_label", "0042_another_migration"),
            ]

            operations = []
        """
    )
    assert_deps_parsed(
        rule_runner,
        content,
        constraints=constraints,
        expected_imports={
            "path.to.app1.migrations.0012_some_migration": ImpInfo(lineno=3, weak=True),
            "another.path.app2.migrations.0042_another_migration": ImpInfo(lineno=4, weak=True),
        },
    )


@skip_unless_python27_present
def test_works_with_python2(rule_runner: RuleRunner) -> None:
    do_test_migration_dependencies(rule_runner, constraints="CPython==2.7.*")


@skip_unless_python37_present
def test_works_with_python37(rule_runner: RuleRunner) -> None:
    do_test_migration_dependencies(rule_runner, constraints="CPython==3.7.*")


@skip_unless_python38_present
def test_works_with_python38(rule_runner: RuleRunner) -> None:
    do_test_migration_dependencies(rule_runner, constraints="CPython==3.8.*")


@skip_unless_python39_present
def test_works_with_python39(rule_runner: RuleRunner) -> None:
    do_test_migration_dependencies(rule_runner, constraints="CPython==3.9.*")
