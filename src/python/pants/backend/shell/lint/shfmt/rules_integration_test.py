# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.shell.lint.shfmt.rules import ShfmtFieldSet, ShfmtRequest
from pants.backend.shell.lint.shfmt.rules import rules as shfmt_rules
from pants.backend.shell.target_types import ShellSourcesGeneratorTarget
from pants.backend.shell.target_types import rules as target_types_rules
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, external_tool, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *shfmt_rules(),
            *config_files.rules(),
            *external_tool.rules(),
            *source_files.rules(),
            *target_types_rules(),
            QueryRule(FmtResult, [ShfmtRequest.Batch]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[ShellSourcesGeneratorTarget],
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
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.shell.lint.shfmt", *(extra_args or ())],
        env_inherit={"PATH"},
    )
    field_sets = [ShfmtFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            ShfmtRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": GOOD_FILE, "BUILD": "shell_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    fmt_result = run_shfmt(rule_runner, [tgt])
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot({"f.sh": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": BAD_FILE, "BUILD": "shell_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    fmt_result = run_shfmt(rule_runner, [tgt])
    assert fmt_result.stdout == "f.sh\n"
    assert fmt_result.output == rule_runner.make_snapshot({"f.sh": GOOD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.sh": GOOD_FILE, "bad.sh": BAD_FILE, "BUILD": "shell_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.sh")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.sh")),
    ]
    fmt_result = run_shfmt(rule_runner, tgts)
    assert "bad.sh\n" == fmt_result.stdout
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.sh": GOOD_FILE, "bad.sh": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "a/f.sh": NEEDS_CONFIG_FILE,
            "a/BUILD": "shell_sources()",
            "a/.editorconfig": "[*.sh]\nswitch_case_indent = true\n",
            "b/f.sh": NEEDS_CONFIG_FILE,
            "b/BUILD": "shell_sources()",
        }
    )
    tgts = [
        rule_runner.get_target(Address("a", relative_file_path="f.sh")),
        rule_runner.get_target(Address("b", relative_file_path="f.sh")),
    ]
    fmt_result = run_shfmt(rule_runner, tgts)
    assert fmt_result.stdout == "a/f.sh\n"
    assert fmt_result.output == rule_runner.make_snapshot(
        {"a/f.sh": FIXED_NEEDS_CONFIG_FILE, "b/f.sh": NEEDS_CONFIG_FILE}
    )
    assert fmt_result.did_change is True


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": NEEDS_CONFIG_FILE, "BUILD": "shell_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    fmt_result = run_shfmt(rule_runner, [tgt], extra_args=["--shfmt-args=-ci"])
    assert fmt_result.stdout == "f.sh\n"
    assert fmt_result.output == rule_runner.make_snapshot({"f.sh": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True
