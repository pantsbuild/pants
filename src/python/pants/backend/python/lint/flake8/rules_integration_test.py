# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.lint.flake8.rules import Flake8FieldSet, Flake8Request
from pants.backend.python.lint.flake8.rules import rules as flake8_rules
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import skip_unless_python27_and_python3_present
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *flake8_rules(),
            *source_files.rules(),
            *config_files.rules(),
            QueryRule(LintResults, [Flake8Request]),
        ],
        target_types=[PythonLibrary],
    )


GOOD_FILE = "print('Nothing suspicious here..')\n"
BAD_FILE = "import typing\n"  # Unused import.


def run_flake8(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.flake8", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    results = rule_runner.request(
        LintResults,
        [
            Flake8Request(Flake8FieldSet.create(tgt) for tgt in targets),
        ],
    )
    return results.results


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_flake8(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert result[0].stdout.strip() == ""
    assert result[0].report is None


def test_passing_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(rule_runner, tgt)


def test_failing_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_flake8(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "f.py:1:1: F401" in result[0].stdout
    assert result[0].report is None


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_library(name='t')"}
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


@skip_unless_python27_and_python3_present
def test_uses_correct_python_version(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": "version: str = 'Py3 > Py2'\n",
            "BUILD": dedent(
                """\
                python_library(name='py2', interpreter_constraints=['==2.7.*'])
                python_library(name='py3', interpreter_constraints=['>=3.6'])
                """
            ),
        }
    )
    py2_tgt = rule_runner.get_target(Address("", target_name="py2", relative_file_path="f.py"))
    py2_result = run_flake8(rule_runner, [py2_tgt])
    assert len(py2_result) == 1
    assert py2_result[0].exit_code == 1
    assert "f.py:1:8: E999 SyntaxError" in py2_result[0].stdout

    py3_tgt = rule_runner.get_target(Address("", target_name="py3", relative_file_path="f.py"))
    py3_result = run_flake8(rule_runner, [py3_tgt])
    assert len(py3_result) == 1
    assert py3_result[0].exit_code == 0
    assert py3_result[0].stdout.strip() == ""

    # Test that we partition incompatible targets when passed in a single batch. We expect Py2
    # to still fail, but Py3 should pass.
    combined_result = run_flake8(rule_runner, [py2_tgt, py3_tgt])
    assert len(combined_result) == 2
    batched_py3_result, batched_py2_result = sorted(
        combined_result, key=lambda result: result.exit_code
    )
    assert batched_py2_result.exit_code == 1
    assert batched_py2_result.partition_description == "['CPython==2.7.*']"
    assert "f.py:1:8: E999 SyntaxError" in batched_py2_result.stdout

    assert batched_py3_result.exit_code == 0
    assert batched_py3_result.partition_description == "['CPython>=3.6']"
    assert batched_py3_result.stdout.strip() == ""


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": BAD_FILE,
            "BUILD": "python_library(name='t')",
            ".flake8": "[flake8]\nignore = F401\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--flake8-config=.flake8"])


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--flake8-args='--ignore=F401'"])


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_flake8(rule_runner, [tgt], extra_args=["--flake8-skip"])
    assert not result


def test_3rdparty_plugin(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"f.py": "'constant' and 'constant2'\n", "BUILD": "python_library(name='t')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_flake8(
        rule_runner, [tgt], extra_args=["--flake8-extra-requirements=flake8-pantsbuild>=2.0,<3"]
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "f.py:1:1: PB11" in result[0].stdout


def test_report_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_flake8(rule_runner, [tgt], extra_args=["--lint-reports-dir='.'"])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert result[0].stdout.strip() == ""
    assert result[0].report is not None
    report_files = rule_runner.request(DigestContents, [result[0].report.digest])
    assert len(report_files) == 1
    assert "f.py:1:1: F401" in report_files[0].content.decode()


def test_type_stubs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"f.pyi": BAD_FILE, "f.py": GOOD_FILE, "BUILD": "python_library(name='t')"}
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
