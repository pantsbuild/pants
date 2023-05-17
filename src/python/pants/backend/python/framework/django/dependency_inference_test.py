# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.dependency_inference import parse_python_dependencies
from pants.backend.python.dependency_inference.rules import (
    PythonImportDependenciesInferenceFieldSet,
)
from pants.backend.python.dependency_inference.rules import rules as core_rules
from pants.backend.python.framework.django import dependency_inference, detect_apps
from pants.backend.python.target_types import PythonSourceTarget
from pants.backend.python.util_rules import pex
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies
from pants.testutil.python_interpreter_selection import (
    skip_unless_python27_present,
    skip_unless_python37_present,
    skip_unless_python38_present,
    skip_unless_python39_present,
)
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *parse_python_dependencies.rules(),
            *stripped_source_files.rules(),
            *pex.rules(),
            *dependency_inference.rules(),
            *detect_apps.rules(),
            *core_rules(),
            QueryRule(InferredDependencies, [dependency_inference.InferDjangoDependencies]),
        ],
        target_types=[PythonSourceTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


def do_test_migration_dependencies(rule_runner: RuleRunner, constraints: str) -> None:
    rule_runner.write_files(
        {
            "BUILD": "python_source(name='t', source='path/to/app0/migrations/0001_initial.py')",
            "path/to/app0/migrations/0001_initial.py": dedent(
                """\
            class Migration(migrations.Migration):
                dependencies = [
                ("app1", "0012_some_migration"),
                ("app2_label", "0042_another_migration"),
                ]

                operations = []
            """
            ),
            "path/to/app1/BUILD": dedent(
                f"""\
                python_source(
                  source="apps.py",
                  interpreter_constraints=['{constraints}'],
                )
                """
            ),
            "path/to/app1/apps.py": dedent(
                """\
                class App1AppConfig(AppConfig):
                    name = "path.to.app1"
                    label = "app1"
                """
            ),
            "path/to/app1/migrations/BUILD": "python_source(source='0012_some_migration.py')",
            "path/to/app1/migrations/0012_some_migration.py": "",
            "another/path/app2/BUILD": dedent(
                f"""\
                python_source(
                  source="apps.py",
                  interpreter_constraints=['{constraints}'],
                )
                """
            ),
            "another/path/app2/apps.py": dedent(
                """\
                class App2AppConfig(AppConfig):
                    name = "another.path.app2"
                    label = "app2_label"
                """
            ),
            "another/path/app2/migrations/BUILD": "python_source(source='0042_another_migration.py')",
            "another/path/app2/migrations/0042_another_migration.py": "",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t"))
    result = rule_runner.request(
        InferredDependencies,
        [
            dependency_inference.InferDjangoDependencies(
                PythonImportDependenciesInferenceFieldSet.create(tgt)
            )
        ],
    )
    assert set(result.include) == {
        Address("another/path/app2/migrations", target_name="migrations"),
        Address("path/to/app1/migrations", target_name="migrations"),
    }


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
