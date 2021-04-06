# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.lint.docformatter.rules import DocformatterFieldSet, DocformatterRequest
from pants.backend.python.lint.docformatter.rules import rules as docformatter_rules
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
            *docformatter_rules(),
            QueryRule(LintResults, (DocformatterRequest,)),
            QueryRule(FmtResult, (DocformatterRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonLibrary],
    )


GOOD_FILE = '"""Good docstring."""\n'
BAD_FILE = '"""Oops, missing a period"""\n'
FIXED_BAD_FILE = '"""Oops, missing a period."""\n'


def run_docformatter(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[tuple[LintResult, ...], FmtResult]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.docformatter", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [DocformatterFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [DocformatterRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            DocformatterRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_docformatter(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.output == get_digest(rule_runner, {"f.py": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_docformatter(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 3
    assert lint_results[0].stderr.strip() == "f.py"
    assert fmt_result.output == get_digest(rule_runner, {"f.py": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_library(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    lint_results, fmt_result = run_docformatter(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 3
    assert lint_results[0].stderr.strip() == "bad.py"
    assert fmt_result.output == get_digest(
        rule_runner, {"good.py": GOOD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    content = '"""\nOne line docstring acting like it\'s multiline.\n"""\n'
    rule_runner.write_files({"f.py": content, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_docformatter(
        rule_runner,
        [tgt],
        extra_args=["--docformatter-args='--make-summary-multi-line'"],
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.output == get_digest(rule_runner, {"f.py": content})
    assert fmt_result.did_change is False


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_docformatter(
        rule_runner, [tgt], extra_args=["--docformatter-skip"]
    )
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False


def test_stub_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.pyi": GOOD_FILE, "bad.pyi": BAD_FILE, "BUILD": "python_library(name='t')"}
    )

    good_tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="good.pyi"))
    lint_results, fmt_result = run_docformatter(rule_runner, [good_tgt])
    assert len(lint_results) == 1 and lint_results[0].exit_code == 0
    assert lint_results[0].stderr == "" and fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, {"good.pyi": GOOD_FILE})
    assert not fmt_result.did_change

    bad_tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.pyi"))
    lint_results, fmt_result = run_docformatter(rule_runner, [bad_tgt])
    assert len(lint_results) == 1 and lint_results[0].exit_code == 3
    assert "bad.pyi" in lint_results[0].stderr
    assert fmt_result.output == get_digest(rule_runner, {"bad.pyi": FIXED_BAD_FILE})
    assert fmt_result.did_change
