# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, List, Optional, Sequence

import pytest

from pants.backend.python.lint.bandit.rules import BanditFieldSet, BanditRequest
from pants.backend.python.lint.bandit.rules import rules as bandit_rules
from pants.backend.python.target_types import InterpreterConstraintsField, PythonLibrary
from pants.core.goals.lint import LintResult, LintResults
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, FileContent
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import skip_unless_python27_and_python3_present
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *bandit_rules(),
            QueryRule(LintResults, (BanditRequest,)),
        ],
    )


GOOD_SOURCE = FileContent("good.py", b"hashlib.sha256()\n")
# MD5 is a insecure hashing function
BAD_SOURCE = FileContent("bad.py", b"hashlib.md5()\n")
PY3_ONLY_SOURCE = FileContent("py3.py", b"version: str = 'Py3 > Py2'\n")


def make_target(
    rule_runner: RuleRunner,
    source_files: List[FileContent],
    *,
    interpreter_constraints: Optional[str] = None,
) -> Target:
    for source_file in source_files:
        rule_runner.create_file(source_file.path, source_file.content.decode())
    return PythonLibrary(
        {
            InterpreterConstraintsField.alias: [interpreter_constraints]
            if interpreter_constraints
            else None
        },
        address=Address("", target_name="target"),
    )


def run_bandit(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
    additional_args: Optional[List[str]] = None,
) -> Sequence[LintResult]:
    args = ["--backend-packages=pants.backend.python.lint.bandit"]
    if config:
        rule_runner.create_file(relpath=".bandit", contents=config)
        args.append("--bandit-config=.bandit")
    if passthrough_args:
        args.append(f"--bandit-args={passthrough_args}")
    if skip:
        args.append("--bandit-skip")
    if additional_args:
        args.extend(additional_args)
    rule_runner.set_options(args)
    results = rule_runner.request(
        LintResults,
        [BanditRequest(BanditFieldSet.create(tgt) for tgt in targets)],
    )
    return results.results


def assert_success(rule_runner: RuleRunner, target: Target, **kwargs: Any) -> None:
    result = run_bandit(rule_runner, [target], **kwargs)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "No issues identified." in result[0].stdout.strip()
    assert result[0].report is None


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    assert_success(rule_runner, target)


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_bandit(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result[0].stdout
    assert result[0].report is None


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    result = run_bandit(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "good.py" not in result[0].stdout
    assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result[0].stdout
    assert result[0].report is None


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE]),
        make_target(rule_runner, [BAD_SOURCE]),
    ]
    result = run_bandit(rule_runner, targets)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "good.py" not in result[0].stdout
    assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result[0].stdout
    assert result[0].report is None


@skip_unless_python27_and_python3_present
def test_uses_correct_python_version(rule_runner: RuleRunner) -> None:
    py2_target = make_target(
        rule_runner, [PY3_ONLY_SOURCE], interpreter_constraints="CPython==2.7.*"
    )
    py2_result = run_bandit(rule_runner, [py2_target])
    assert len(py2_result) == 1
    assert py2_result[0].exit_code == 0
    assert "py3.py (syntax error while parsing AST from file)" in py2_result[0].stdout

    py3_target = make_target(rule_runner, [PY3_ONLY_SOURCE], interpreter_constraints="CPython>=3.6")
    py3_result = run_bandit(rule_runner, [py3_target])
    assert len(py3_result) == 1
    assert py3_result[0].exit_code == 0
    assert "No issues identified." in py3_result[0].stdout

    # Test that we partition incompatible targets when passed in a single batch. We expect Py2
    # to still fail, but Py3 should pass.
    combined_result = run_bandit(rule_runner, [py2_target, py3_target])
    assert len(combined_result) == 2

    batched_py2_result, batched_py3_result = sorted(
        combined_result, key=lambda result: result.stderr
    )
    assert batched_py2_result.exit_code == 0
    assert batched_py2_result.partition_description == "['CPython==2.7.*']"
    assert "py3.py (syntax error while parsing AST from file)" in batched_py2_result.stdout

    assert batched_py3_result.exit_code == 0
    assert batched_py3_result.partition_description == "['CPython>=3.6']"
    assert "No issues identified." in batched_py3_result.stdout


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    assert_success(rule_runner, target, config="skips: ['B303']\n")


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    assert_success(rule_runner, target, passthrough_args="--skip B303")


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_bandit(rule_runner, [target], skip=True)
    assert not result


def test_3rdparty_plugin(rule_runner: RuleRunner) -> None:
    target = make_target(
        rule_runner,
        [FileContent("bad.py", b"aws_key = 'JalrXUtnFEMI/K7MDENG/bPxRfiCYzEXAMPLEKEY'\n")],
        # NB: `bandit-aws` does not currently work with Python 3.8. See
        #  https://github.com/pantsbuild/pants/issues/10545.
        interpreter_constraints="CPython>=3.6,<3.8",
    )
    result = run_bandit(
        rule_runner, [target], additional_args=["--bandit-extra-requirements=bandit-aws"]
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "Issue: [C100:hardcoded_aws_key]" in result[0].stdout
    assert result[0].report is None


def test_report_file(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_bandit(rule_runner, [target], additional_args=["--lint-reports-dir='.'"])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert result[0].stdout.strip() == ""
    assert result[0].report is not None
    report_files = rule_runner.request(DigestContents, [result[0].report.digest])
    assert len(report_files) == 1
    assert (
        "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in report_files[0].content.decode()
    )


def test_type_stubs(rule_runner: RuleRunner) -> None:
    """Ensure that running over a type stub file doesn't cause issues."""
    type_stub = FileContent("good.pyi", b"def add(x: int, y: int) -> int:\n  return x + y")
    # First check when the stub has no sibling `.py` file.
    target = make_target(rule_runner, [type_stub])
    assert_success(rule_runner, target)
    # Then check with a sibling `.py`.
    target = make_target(rule_runner, [GOOD_SOURCE, type_stub])
    assert_success(rule_runner, target)
