# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from textwrap import dedent
from typing import List, Optional, Sequence, Tuple

import pytest
from pytest import mark

from pants.backend.python.lint.autoflake.rules import AutoflakeFieldSet, AutoflakeRequest
from pants.backend.python.lint.autoflake.rules import rules as autoflake_rules
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *autoflake_rules(),
            QueryRule(LintResults, (AutoflakeRequest,)),
            QueryRule(FmtResult, (AutoflakeRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ]
    )


GOOD_SOURCE = FileContent(
    "good.py", b"from typing import List, cast\nx: List[float] = [cast(float, 1)]"
)
BAD_SOURCE = FileContent("bad.py", b"from typing import List, cast\nx: List[float] = [1]")
FIXED_BAD_SOURCE = FileContent("bad.py", b"from typing import List\nx: List[float] = [1]")


def make_target(rule_runner: RuleRunner, source_files: List[FileContent]) -> Target:
    for source_file in source_files:
        rule_runner.create_file(f"{source_file.path}", source_file.content.decode())
    return PythonLibrary({}, address=Address("", target_name="target"))


def run_autoflake(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
) -> Tuple[Sequence[LintResult], FmtResult]:
    args = ["--backend-packages=pants.backend.python.lint.autoflake"]
    if passthrough_args:
        args.append(f"--autoflake-args='{passthrough_args}'")
    if skip:
        args.append("--autoflake-skip")
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    field_sets = [AutoflakeFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [AutoflakeRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            AutoflakeRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: List[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    lint_results, fmt_result = run_autoflake(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert "No issues detected!" in lint_results[0].stdout
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE])
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_autoflake(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.py: Unused" in lint_results[0].stdout
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, [FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    lint_results, fmt_result = run_autoflake(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.py: Unused" in lint_results[0].stdout
    assert "good.py" not in lint_results[0].stdout
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE]),
        make_target(rule_runner, [BAD_SOURCE]),
    ]
    lint_results, fmt_result = run_autoflake(rule_runner, targets)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.py: Unused" in lint_results[0].stdout
    assert "good.py" not in lint_results[0].stdout
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


@mark.parametrize("args", ["--remove-all-unused-imports", "--imports=pandas"])
def test_respects_passthrough_args(rule_runner: RuleRunner, args: str) -> None:
    bad_file = FileContent(
        "bad.py",
        dedent(
            """
            from typing import List, cast

            from pandas import DataFrame

            x: List[float] = [1]

            def f(x):  # useless pass
                print(x)
                pass
            """
        ).encode(),
    )
    fixed_file = FileContent(
        "bad.py",
        dedent(
            """
            from typing import List


            x: List[float] = [1]

            def f(x):  # useless pass
                print(x)
            """
        ).encode(),
    )
    target = make_target(rule_runner, [bad_file])
    lint_results, fmt_result = run_autoflake(rule_runner, [target], passthrough_args=args)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.py: Unused" in lint_results[0].stdout
    assert lint_results[0].stderr == ""
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, [fixed_file]), fmt_result.output
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_autoflake(rule_runner, [target], skip=True)
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False


def test_stub_files(rule_runner: RuleRunner) -> None:
    good_stub = dataclasses.replace(GOOD_SOURCE, path="good.pyi")
    bad_stub = dataclasses.replace(BAD_SOURCE, path="bad.pyi")
    fixed_bad_stub = dataclasses.replace(FIXED_BAD_SOURCE, path="bad.pyi")

    good_files = [GOOD_SOURCE, good_stub]
    target = make_target(rule_runner, good_files)
    lint_results, fmt_result = run_autoflake(rule_runner, [target])
    assert len(lint_results) == 1 and lint_results[0].exit_code == 0
    assert (
        lint_results[0].stderr == ""
        and "No issues detected!" in lint_results[0].stdout
        and fmt_result.stdout == ""
    )
    assert fmt_result.output == get_digest(rule_runner, good_files)
    assert not fmt_result.did_change

    target = make_target(rule_runner, [BAD_SOURCE, bad_stub])
    lint_results, fmt_result = run_autoflake(rule_runner, [target])
    assert len(lint_results) == 1 and lint_results[0].exit_code == 1
    assert "bad.pyi: Unused" in lint_results[0].stdout
    assert fmt_result.stdout == ""
    fixed_bad_files = [FIXED_BAD_SOURCE, fixed_bad_stub]
    assert fmt_result.output == get_digest(rule_runner, [*fixed_bad_files, *good_files])
    assert fmt_result.did_change
