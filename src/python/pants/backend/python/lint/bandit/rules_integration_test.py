# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Sequence
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.bandit.rules import BanditRequest
from pants.backend.python.lint.bandit.rules import rules as bandit_rules
from pants.backend.python.lint.bandit.subsystem import BanditFieldSet
from pants.backend.python.lint.bandit.subsystem import rules as bandit_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, DigestContents
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import (
    all_major_minor_python_versions,
    has_python_version,
    skip_unless_python310_and_python311_present,
)
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.util.resources import read_sibling_resource


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *bandit_rules(),
            *bandit_subsystem_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(Partitions, [BanditRequest.PartitionRequest]),
            QueryRule(LintResult, [BanditRequest.Batch]),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = "hashlib.sha256()\n"
BAD_FILE = "hashlib.md5()\n"  # An insecure hashing function.


def run_bandit(
    rule_runner: PythonRuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> Sequence[LintResult]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python.lint.bandit",
            *(extra_args or ()),
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    partitions = rule_runner.request(
        Partitions[BanditFieldSet, InterpreterConstraints],
        [BanditRequest.PartitionRequest(tuple(BanditFieldSet.create(tgt) for tgt in targets))],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [BanditRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def assert_success(
    rule_runner: PythonRuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_bandit(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "No issues identified." in result[0].stdout.strip()
    assert result[0].report == EMPTY_DIGEST


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(["CPython>=3.9,<3.15"]),
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
    result = run_bandit(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "Issue: [B324:hashlib] Use of weak MD5 hash for security." in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_multiple_targets(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    result = run_bandit(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "good.py" not in result[0].stdout
    assert "Issue: [B324:hashlib] Use of weak MD5 hash for security." in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


@skip_unless_python310_and_python311_present
def test_uses_correct_python_version(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": "eg = ExceptionGroup('', [Exception()])'\n",
            "BUILD": dedent(
                """\
                python_sources(name="py310", interpreter_constraints=["==3.10.*"])
                python_sources(name="py311", interpreter_constraints=["==3.11.*"])
                """
            ),
        }
    )

    py310_tgt = rule_runner.get_target(Address("", target_name="py310", relative_file_path="f.py"))
    py310_result = run_bandit(rule_runner, [py310_tgt])
    assert len(py310_result) == 1
    assert py310_result[0].exit_code == 0
    assert "f.py (syntax error while parsing AST from file)" in py310_result[0].stdout

    py311_tgt = rule_runner.get_target(Address("", target_name="py311", relative_file_path="f.py"))
    py311_result = run_bandit(rule_runner, [py311_tgt])
    assert len(py311_result) == 1
    assert py311_result[0].exit_code == 0
    assert "No issues identified." in py311_result[0].stdout

    # Test that we partition incompatible targets when passed in a single batch. We expect Py38
    # to still fail, but Py39 should pass.
    combined_result = run_bandit(rule_runner, [py310_tgt, py311_tgt])
    assert len(combined_result) == 2

    batched_py310_result, batched_py311_result = sorted(
        combined_result, key=lambda result: result.stderr
    )
    assert batched_py310_result.exit_code == 0
    assert batched_py310_result.partition_description == "['CPython==3.10.*']"
    assert "f.py (syntax error while parsing AST from file)" in batched_py310_result.stdout

    assert batched_py311_result.exit_code == 0
    assert batched_py311_result.partition_description == "['CPython==3.11.*']"
    assert "No issues identified." in batched_py311_result.stdout


def test_respects_config_file(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": BAD_FILE,
            "BUILD": "python_sources(name='t')",
            ".bandit": "skips: ['B324']",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--bandit-config=.bandit"])


def test_respects_passthrough_args(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--bandit-args='--skip=B324'"])


def test_skip(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_bandit(rule_runner, [tgt], extra_args=["--bandit-skip"])
    assert not result


@pytest.mark.skipif(not (has_python_version("3.11")), reason="Missing Python 3.11")
def test_3rdparty_plugin(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": "aws_key = 'JalrXUtnFEMI/K7MDENG/bPxRfiCYzEXAMPLEKEY'\n",
            "BUILD": "python_sources(name='t', interpreter_constraints=['>=3.11,<3.12'])",
            "bandit.lock": read_sibling_resource(__name__, "bandit_plugin_test.lock"),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_bandit(
        rule_runner,
        [tgt],
        extra_args=[
            "--python-resolves={'bandit':'bandit.lock'}",
            "--bandit-install-from-resolve=bandit",
        ],
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "Issue: [C100:hardcoded_aws_key]" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_report_file(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    result = run_bandit(
        rule_runner, [tgt], extra_args=["--bandit-args='--output=reports/output.txt'"]
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert result[0].stdout.strip() == ""
    report_files = rule_runner.request(DigestContents, [result[0].report])
    assert len(report_files) == 1
    assert (
        "Issue: [B324:hashlib] Use of weak MD5 hash for security."
        in report_files[0].content.decode()
    )


def test_type_stubs(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.pyi": BAD_FILE,
            "f.py": GOOD_FILE,
            "BUILD": "python_sources(name='t')",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="f.pyi")),
    ]
    result = run_bandit(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "f.py " not in result[0].stdout
    assert "f.pyi" in result[0].stdout
    assert "Issue: [B324:hashlib] Use of weak MD5 hash for security." in result[0].stdout
    assert result[0].report == EMPTY_DIGEST
