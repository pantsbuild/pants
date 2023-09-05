# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.flake8.rules import Flake8Request
from pants.backend.python.lint.flake8.rules import rules as flake8_rules
from pants.backend.python.lint.flake8.subsystem import Flake8FieldSet
from pants.backend.python.lint.flake8.subsystem import rules as flake8_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import python_sources
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, DigestContents
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import (
    all_major_minor_python_versions,
    skip_unless_python37_and_python39_present,
)
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.util.resources import read_sibling_resource


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *flake8_rules(),
            *flake8_subsystem_rules(),
            *python_sources.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(Partitions, [Flake8Request.PartitionRequest]),
            QueryRule(LintResult, [Flake8Request.Batch]),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = "print('Nothing suspicious here..')\n"
BAD_FILE = "import typing\n"  # Unused import.


def run_flake8(
    rule_runner: PythonRuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.flake8", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    partitions = rule_runner.request(
        Partitions[Flake8FieldSet, Any],
        [Flake8Request.PartitionRequest(tuple(Flake8FieldSet.create(tgt) for tgt in targets))],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [Flake8Request.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def assert_success(
    rule_runner: PythonRuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_flake8(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert result[0].stdout.strip() == ""
    assert result[0].report == EMPTY_DIGEST


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(["CPython>=3.7,<4"]),
)
def test_passing(rule_runner: PythonRuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(
        rule_runner,
        tgt,
        extra_args=[f"--python-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )


def test_failing(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_flake8(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "f.py:1:1: F401" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_multiple_targets(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    result = run_flake8(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "good.py" not in result[0].stdout
    assert "bad.py:1:1: F401" in result[0].stdout


@skip_unless_python37_and_python39_present
def test_uses_correct_python_version(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": "y = (x := 5)\n",
            "BUILD": dedent(
                """\
                python_sources(name='py37', interpreter_constraints=['CPython==3.7.*'])
                python_sources(name='py39', interpreter_constraints=['CPython==3.9.*'])
                """
            ),
        }
    )

    py37_tgt = rule_runner.get_target(Address("", target_name="py37", relative_file_path="f.py"))
    py37_result = run_flake8(rule_runner, [py37_tgt])
    assert len(py37_result) == 1
    assert py37_result[0].exit_code == 1
    assert "f.py:1:8: E999 SyntaxError" in py37_result[0].stdout

    py39_tgt = rule_runner.get_target(Address("", target_name="py39", relative_file_path="f.py"))
    py39_result = run_flake8(rule_runner, [py39_tgt])
    assert len(py39_result) == 1
    assert py39_result[0].exit_code == 0
    assert py39_result[0].stdout.strip() == ""

    # Test that we partition incompatible targets when passed in a single batch. We expect Py37
    # to still fail, but Py39 should pass.
    combined_result = run_flake8(rule_runner, [py37_tgt, py39_tgt])
    assert len(combined_result) == 2
    batched_py39_result, batched_py37_result = sorted(
        combined_result, key=lambda result: result.exit_code
    )
    assert batched_py37_result.exit_code == 1
    assert batched_py37_result.partition_description == "['CPython==3.7.*']"
    assert "f.py:1:8: E999 SyntaxError" in batched_py37_result.stdout

    assert batched_py39_result.exit_code == 0
    assert batched_py39_result.partition_description == "['CPython==3.9.*']"
    assert batched_py39_result.stdout.strip() == ""


@pytest.mark.parametrize(
    "config_path,extra_args",
    ([".flake8", []], ["custom_config.ini", ["--flake8-config=custom_config.ini"]]),
)
def test_config_file(
    rule_runner: PythonRuleRunner, config_path: str, extra_args: list[str]
) -> None:
    rule_runner.write_files(
        {
            "f.py": BAD_FILE,
            "BUILD": "python_sources(name='t')",
            config_path: "[flake8]\nignore = F401\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=extra_args)


def test_passthrough_args(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--flake8-args='--ignore=F401'"])


def test_skip(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_flake8(rule_runner, [tgt], extra_args=["--flake8-skip"])
    assert not result


def test_3rdparty_plugin(rule_runner: PythonRuleRunner) -> None:
    # Test extra_files option.
    rule_runner.write_files(
        {
            "f.py": "assert 1 == 1\n",
            ".bandit": "[bandit]\nskips: B101\n",
            "BUILD": "python_sources(name='t')",
            "flake8.lock": read_sibling_resource(__name__, "flake8_plugin_test.lock"),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_flake8(
        rule_runner,
        [tgt],
        extra_args=[
            "--python-resolves={'flake8':'flake8.lock'}",
            "--flake8-install-from-resolve=flake8",
            "--flake8-extra-files=['.bandit']",
        ],
    )
    assert len(result) == 1
    assert result[0].exit_code == 0, result[0].stderr


def test_report_file(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_flake8(
        rule_runner, [tgt], extra_args=["--flake8-args='--output-file=reports/foo.txt'"]
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert result[0].stdout.strip() == ""
    report_files = rule_runner.request(DigestContents, [result[0].report])
    assert len(report_files) == 1
    assert "f.py:1:1: F401" in report_files[0].content.decode()


def test_type_stubs(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {"f.pyi": BAD_FILE, "f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="f.pyi")),
    ]
    result = run_flake8(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "f.py:" not in result[0].stdout
    assert "f.pyi:1:1: F401" in result[0].stdout
