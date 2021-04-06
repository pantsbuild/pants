# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.lint.black.rules import BlackFieldSet, BlackRequest
from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import source_files, warn_config_files_not_setup
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import (
    skip_unless_python38_present,
    skip_unless_python39_present,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *black_rules(),
            *source_files.rules(),
            *warn_config_files_not_setup.rules(),
            QueryRule(LintResults, (BlackRequest,)),
            QueryRule(FmtResult, (BlackRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonLibrary],
    )


GOOD_FILE = 'animal = "Koala"\n'
BAD_FILE = 'name=    "Anakin"\n'
FIXED_BAD_FILE = 'name = "Anakin"\n'
NEEDS_CONFIG_FILE = "animal = 'Koala'\n"  # Note the single quotes.


def run_black(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[tuple[LintResult, ...], FmtResult]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.black", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [BlackFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [BlackRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            BlackRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_black(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, {"f.py": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_black(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "1 file would be reformatted" in lint_results[0].stderr
    assert "1 file reformatted" in fmt_result.stderr
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
    lint_results, fmt_result = run_black(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "1 file would be reformatted, 1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file reformatted, 1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(
        rule_runner, {"good.py": GOOD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.py": NEEDS_CONFIG_FILE,
            "pyproject.toml": "[tool.black]\nskip-string-normalization = 'true'\n",
            "BUILD": "python_library(name='t')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_black(
        rule_runner, [tgt], extra_args=["--black-config=pyproject.toml"]
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, {"f.py": NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is False


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": NEEDS_CONFIG_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_black(
        rule_runner, [tgt], extra_args=["--black-args='--skip-string-normalization'"]
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, {"f.py": NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is False


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_black(rule_runner, [tgt], extra_args=["--black-skip"])
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False


@skip_unless_python38_present
def test_works_with_python38(rule_runner: RuleRunner) -> None:
    """Black's typed-ast dependency does not understand Python 3.8, so we must instead run Black
    with Python 3.8 when relevant."""
    content = dedent(
        """\
        import datetime

        x = True
        if y := x:
            print("x is truthy and now assigned to y")


        class Foo:
            pass
        """
    )
    rule_runner.write_files(
        {"f.py": content, "BUILD": "python_library(name='t', interpreter_constraints=['>=3.8'])"}
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_black(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, {"f.py": content})
    assert fmt_result.did_change is False


@skip_unless_python39_present
def test_works_with_python39(rule_runner: RuleRunner) -> None:
    """Black's typed-ast dependency does not understand Python 3.9, so we must instead run Black
    with Python 3.9 when relevant."""
    content = dedent(
        """\
        @lambda _: int
        def replaced(x: bool) -> str:
            return "42" if x is True else "1/137"
        """
    )
    rule_runner.write_files(
        {"f.py": content, "BUILD": "python_library(name='t', interpreter_constraints=['>=3.9'])"}
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    lint_results, fmt_result = run_black(
        rule_runner,
        [tgt],
        # TODO: remove this and go back to using the default version once the new Black release
        #  comes out.
        extra_args=[
            "--black-version=Black@ git+https://github.com/psf/black.git@aebd3c37b28bbc0183a58d13b80e7595db3c09bb"
        ],
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert "1 file would be left unchanged" in lint_results[0].stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == get_digest(rule_runner, {"f.py": content})
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
    lint_results, fmt_result = run_black(rule_runner, good_tgts)
    assert len(lint_results) == 1 and lint_results[0].exit_code == 0
    assert (
        "2 files would be left unchanged" in lint_results[0].stderr
        and "2 files left unchanged" in fmt_result.stderr
    )
    assert fmt_result.output == get_digest(
        rule_runner, {"good.pyi": GOOD_FILE, "good.py": GOOD_FILE}
    )
    assert not fmt_result.did_change

    bad_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    lint_results, fmt_result = run_black(rule_runner, bad_tgts)
    assert len(lint_results) == 1 and lint_results[0].exit_code == 1
    assert (
        "2 files would be reformatted" in lint_results[0].stderr
        and "2 files reformatted" in fmt_result.stderr
    )
    assert fmt_result.output == get_digest(
        rule_runner, {"bad.pyi": FIXED_BAD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change
