# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.lint.isort.rules import IsortFieldSet, IsortRequest
from pants.backend.python.lint.isort.rules import rules as isort_rules
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
            *isort_rules(),
            QueryRule(LintResults, (IsortRequest,)),
            QueryRule(FmtResult, (IsortRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonLibrary],
    )


GOOD_FILE = "from animals import cat, dog\n"
BAD_FILE = "from colors import green, blue\n"
FIXED_BAD_FILE = "from colors import blue, green\n"

# Note the `as` import is a new line.
NEEDS_CONFIG_FILE = "from colors import blue\nfrom colors import green as verde\n"
FIXED_NEEDS_CONFIG_FILE = "from colors import blue, green as verde\n"


def run_isort(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> tuple[tuple[LintResult, ...], FmtResult]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.isort", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [IsortFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [IsortRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            IsortRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_isort(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, {"f.py": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_isort(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "f.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert fmt_result.stdout == "Fixing f.py\n"
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
    lint_results, fmt_result = run_isort(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert "good.py" not in lint_results[0].stderr
    assert "Fixing bad.py\n" == fmt_result.stdout
    assert fmt_result.output == get_digest(
        rule_runner, {"good.py": GOOD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": NEEDS_CONFIG_FILE,
            "BUILD": "python_library(name='t')",
            ".isort.cfg": "[settings]\ncombine_as_imports=True\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_isort(
        rule_runner, [tgt], extra_args=["--isort-config=.isort.cfg"]
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "f.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert fmt_result.stdout == "Fixing f.py\n"
    assert fmt_result.output == get_digest(rule_runner, {"f.py": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": NEEDS_CONFIG_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_isort(
        rule_runner, [tgt], extra_args=["--isort-args='--combine-as'"]
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "f.py Imports are incorrectly sorted" in lint_results[0].stderr
    assert fmt_result.stdout == "Fixing f.py\n"
    assert fmt_result.output == get_digest(rule_runner, {"f.py": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_isort(rule_runner, [tgt], extra_args=["--isort-skip"])
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False


def test_stub_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.pyi": GOOD_FILE,
            "good.py": GOOD_FILE,
            "bad.pyi": BAD_FILE,
            "bad.py": BAD_FILE,
            "BUILD": "python_library(name='t')",
        }
    )

    good_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
    ]
    lint_results, fmt_result = run_isort(rule_runner, good_tgts)
    assert len(lint_results) == 1 and lint_results[0].exit_code == 0
    assert lint_results[0].stderr == "" and fmt_result.stdout == ""
    assert fmt_result.output == get_digest(
        rule_runner, {"good.py": GOOD_FILE, "good.pyi": GOOD_FILE}
    )
    assert not fmt_result.did_change

    bad_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    lint_results, fmt_result = run_isort(rule_runner, bad_tgts)
    assert len(lint_results) == 1 and lint_results[0].exit_code == 1
    assert "bad.pyi Imports are incorrectly sorted" in lint_results[0].stderr
    assert fmt_result.stdout == "Fixing bad.py\nFixing bad.pyi\n"
    assert fmt_result.output == get_digest(
        rule_runner, {"bad.py": FIXED_BAD_FILE, "bad.pyi": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change
