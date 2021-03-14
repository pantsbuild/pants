# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, List, Optional, Sequence

import pytest

from pants.backend.python.lint.flake8.rules import Flake8FieldSet, Flake8Request
from pants.backend.python.lint.flake8.rules import rules as flake8_rules
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
            *flake8_rules(),
            QueryRule(LintResults, (Flake8Request,)),
        ]
    )


GOOD_SOURCE = FileContent("good.py", b"print('Nothing suspicious here..')\n")
BAD_SOURCE = FileContent("bad.py", b"import typing\n")  # unused import
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


def run_flake8(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
    additional_args: Optional[List[str]] = None,
) -> Sequence[LintResult]:
    args = ["--backend-packages=pants.backend.python.lint.flake8"]
    if config:
        rule_runner.create_file(relpath=".flake8", contents=config)
        args.append("--flake8-config=.flake8")
    if passthrough_args:
        args.append(f"--flake8-args='{passthrough_args}'")
    if skip:
        args.append("--flake8-skip")
    if additional_args:
        args.extend(additional_args)
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    results = rule_runner.request(
        LintResults,
        [
            Flake8Request(Flake8FieldSet.create(tgt) for tgt in targets),
        ],
    )
    return results.results


def assert_success(rule_runner: RuleRunner, target: Target, **kwargs: Any) -> None:
    result = run_flake8(rule_runner, [target], **kwargs)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert result[0].stdout.strip() == ""
    assert result[0].report is None


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    assert_success(rule_runner, target)


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_flake8(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "bad.py:1:1: F401" in result[0].stdout
    assert result[0].report is None


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    result = run_flake8(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "good.py" not in result[0].stdout
    assert "bad.py:1:1: F401" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE]),
        make_target(rule_runner, [BAD_SOURCE]),
    ]
    result = run_flake8(rule_runner, targets)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "good.py" not in result[0].stdout
    assert "bad.py:1:1: F401" in result[0].stdout


@skip_unless_python27_and_python3_present
def test_uses_correct_python_version(rule_runner: RuleRunner) -> None:
    py2_target = make_target(
        rule_runner, [PY3_ONLY_SOURCE], interpreter_constraints="CPython==2.7.*"
    )
    py2_result = run_flake8(rule_runner, [py2_target])
    assert len(py2_result) == 1
    assert py2_result[0].exit_code == 1
    assert "py3.py:1:8: E999 SyntaxError" in py2_result[0].stdout

    py3_target = make_target(rule_runner, [PY3_ONLY_SOURCE], interpreter_constraints="CPython>=3.6")
    py3_result = run_flake8(rule_runner, [py3_target])
    assert len(py3_result) == 1
    assert py3_result[0].exit_code == 0
    assert py3_result[0].stdout.strip() == ""

    # Test that we partition incompatible targets when passed in a single batch. We expect Py2
    # to still fail, but Py3 should pass.
    combined_result = run_flake8(rule_runner, [py2_target, py3_target])
    assert len(combined_result) == 2
    batched_py3_result, batched_py2_result = sorted(
        combined_result, key=lambda result: result.exit_code
    )
    assert batched_py2_result.exit_code == 1
    assert batched_py2_result.partition_description == "['CPython==2.7.*']"
    assert "py3.py:1:8: E999 SyntaxError" in batched_py2_result.stdout

    assert batched_py3_result.exit_code == 0
    assert batched_py3_result.partition_description == "['CPython>=3.6']"
    assert batched_py3_result.stdout.strip() == ""


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    assert_success(rule_runner, target, config="[flake8]\nignore = F401\n")


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    assert_success(rule_runner, target, passthrough_args="--ignore=F401")


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_flake8(rule_runner, [target], skip=True)
    assert not result


def test_3rdparty_plugin(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [FileContent("bad.py", b"'constant' and 'constant2'\n")])
    result = run_flake8(
        rule_runner,
        [target],
        additional_args=["--flake8-extra-requirements=flake8-pantsbuild>=2.0,<3"],
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "bad.py:1:1: PB11" in result[0].stdout


def test_report_file(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_flake8(rule_runner, [target], additional_args=["--lint-reports-dir='.'"])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert result[0].stdout.strip() == ""
    assert result[0].report is not None
    report_files = rule_runner.request(DigestContents, [result[0].report.digest])
    assert len(report_files) == 1
    assert "bad.py:1:1: F401" in report_files[0].content.decode()


def test_type_stubs(rule_runner: RuleRunner) -> None:
    """Ensure that running over a type stub file doesn't cause issues."""
    type_stub = FileContent("good.pyi", b"def add(x: int, y: int) -> int:\n    return x + y\n")
    # First check when the stub has no sibling `.py` file.
    target = make_target(rule_runner, [type_stub])
    assert_success(rule_runner, target)
    # Then check with a sibling `.py`.
    target = make_target(rule_runner, [GOOD_SOURCE, type_stub])
    assert_success(rule_runner, target)
