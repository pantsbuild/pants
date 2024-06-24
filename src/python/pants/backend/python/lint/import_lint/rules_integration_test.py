# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from import_lint.lint_request import ImportLintercheckFieldSet, ImportLinterRequest
from import_lint.rules import rules as import_linter_rules
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, DigestContents
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner

from pants.testutil.python_interpreter_selection import (
    all_major_minor_python_versions,
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *import_linter_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(LintResults, [ImportLinterRequest]),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )

GOOD_FILE = "print('Nothing suspicious here..')\n"
BAD_FILE = "import typing\n"  # Unused import.

def run_import_linter(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    
    rule_runner.set_options(
        ["--backend-packages=import_lint"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME",},
    )
    results = rule_runner.request(
        LintResults,
        [
            ImportLinterRequest(ImportLintercheckFieldSet.create(tgt) for tgt in targets),
        ],
    )
    return results.results

def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_import_linter(rule_runner, [target], extra_args=extra_args)
    assert result == ""
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert result[0].stdout.strip() == ""
    assert result[0].report == EMPTY_DIGEST


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({
        "myproject/f.py": GOOD_FILE,
        "BUILD": "python_sources(name='t2', sources=['**/*.py', '__init__.py', 'setup.py'])",
        "__init__.py": "",
        "setup.py": """
from setuptools import setup

setup(
    **{
        "name": "myproject",
        "version": "0.1.0",
    }
)
        """,
        ".importlinter": """
[importlinter]
root_package = myproject

[importlinter:contract:1]
name=Foo doesn't import bar or baz
type=forbidden
source_modules=
    myproject.foo
forbidden_modules=
    myproject.bar
    myproject.baz
"""
    })
    tgt = rule_runner.get_target(Address("", target_name="t2", relative_file_path="myproject/f.py"))
    assert_success(
        rule_runner,
        tgt,
        extra_args=[],
    )