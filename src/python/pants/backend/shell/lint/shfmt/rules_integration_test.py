# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.shell.lint.shfmt.rules import ShfmtFieldSet, ShfmtRequest
from pants.backend.shell.lint.shfmt.rules import rules as shfmt_rules
from pants.backend.shell.target_types import ShellLibrary
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import external_tool, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *shfmt_rules(),
            *external_tool.rules(),
            *source_files.rules(),
            QueryRule(LintResults, [ShfmtRequest]),
            QueryRule(FmtResult, [ShfmtRequest]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[ShellLibrary],
    )


GOOD_FILE = "! foo bar >a &\n"
BAD_FILE = "!    foo bar >a  &\n"

# If config is loaded correctly, shfmt will indent the case statements.
NEEDS_CONFIG_FILE = dedent(
    """\
    case foo in
    PATTERN_1)
    \tbar
    \t;;
    *)
    \tbaz
    \t;;
    esac
    """
)
FIXED_NEEDS_CONFIG_FILE = dedent(
    """\
    case foo in
    \tPATTERN_1)
    \t\tbar
    \t\t;;
    \t*)
    \t\tbaz
    \t\t;;
    esac
    """
)


def run_shfmt(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> tuple[tuple[LintResult, ...], FmtResult]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.shell.lint.shfmt", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [ShfmtFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [ShfmtRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            ShfmtRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": GOOD_FILE, "BUILD": "shell_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    lint_results, fmt_result = run_shfmt(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, {"f.sh": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": BAD_FILE, "BUILD": "shell_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    lint_results, fmt_result = run_shfmt(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "f.sh.orig" in lint_results[0].stdout
    assert fmt_result.stdout == "f.sh\n"
    assert fmt_result.output == get_digest(rule_runner, {"f.sh": GOOD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.sh": GOOD_FILE, "bad.sh": BAD_FILE, "BUILD": "shell_library(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.sh")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.sh")),
    ]
    lint_results, fmt_result = run_shfmt(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.sh.orig" in lint_results[0].stdout
    assert "good.sh" not in lint_results[0].stdout
    assert "bad.sh\n" == fmt_result.stdout
    assert fmt_result.output == get_digest(rule_runner, {"good.sh": GOOD_FILE, "bad.sh": GOOD_FILE})
    assert fmt_result.did_change is True


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.sh": NEEDS_CONFIG_FILE,
            "BUILD": "shell_library(name='t')",
            ".editorconfig": "[*.sh]\nswitch_case_indent = true\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    lint_results, fmt_result = run_shfmt(
        rule_runner, [tgt], extra_args=["--shfmt-config=.editorconfig"]
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "f.sh.orig" in lint_results[0].stdout
    assert fmt_result.stdout == "f.sh\n"
    assert fmt_result.output == get_digest(rule_runner, {"f.sh": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": NEEDS_CONFIG_FILE, "BUILD": "shell_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    lint_results, fmt_result = run_shfmt(
        rule_runner, [tgt], extra_args=["--shfmt-args=-ci"]
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "f.sh.orig" in lint_results[0].stdout
    assert fmt_result.stdout == "f.sh\n"
    assert fmt_result.output == get_digest(rule_runner, {"f.sh": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": BAD_FILE, "BUILD": "shell_library(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    lint_results, fmt_result = run_shfmt(rule_runner, [tgt], extra_args=["--shfmt-skip"])
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False
