# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Sequence

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.pydocstyle.rules import PydocstyleRequest
from pants.backend.python.lint.pydocstyle.rules import rules as pydocstyle_rules
from pants.backend.python.lint.pydocstyle.subsystem import PydocstyleFieldSet
from pants.backend.python.lint.pydocstyle.subsystem import rules as pydocstyle_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pydocstyle_rules(),
            *pydocstyle_subsystem_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(Partitions, [PydocstyleRequest.PartitionRequest]),
            QueryRule(LintResult, [PydocstyleRequest.Batch]),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = '''
"""Public module docstring is present."""
def fun():
  """Pretty docstring is present."""
  pass
'''
BAD_FILE = """
def fun():
  '''ugly docstring!'''
  pass
"""


def run_pydocstyle(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> Sequence[LintResult]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python.lint.pydocstyle",
            *(extra_args or ()),
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    partitions = rule_runner.request(
        Partitions[PydocstyleFieldSet, InterpreterConstraints],
        [
            PydocstyleRequest.PartitionRequest(
                tuple(PydocstyleFieldSet.create(tgt) for tgt in targets)
            )
        ],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [PydocstyleRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_pydocstyle(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(["CPython>=3.7,<4"]),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(
        rule_runner,
        tgt,
        extra_args=[f"--python-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_pydocstyle(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "D100: Missing docstring in public module" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    result = run_pydocstyle(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "good.py" not in result[0].stdout
    assert "D400: First line should end with a period (not '!')" in result[0].stdout


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": BAD_FILE,
            "BUILD": "python_sources(name='t')",
            ".pydocstyle.ini": "[pydocstyle]\nignore = D100,D300,D400,D403",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--pydocstyle-config=.pydocstyle.ini"])


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(
        rule_runner, tgt, extra_args=["--pydocstyle-args='--ignore=D100,D300,D400,D403'"]
    )


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_pydocstyle(rule_runner, [tgt], extra_args=["--pydocstyle-skip"])
    assert not result
