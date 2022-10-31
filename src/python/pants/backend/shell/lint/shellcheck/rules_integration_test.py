# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any

import pytest

from pants.backend.shell.lint.shellcheck.rules import ShellcheckFieldSet, ShellcheckRequest
from pants.backend.shell.lint.shellcheck.rules import rules as shellcheck_rules
from pants.backend.shell.target_types import ShellSourcesGeneratorTarget
from pants.backend.shell.target_types import rules as target_types_rules
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, external_tool, source_files
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *shellcheck_rules(),
            *config_files.rules(),
            *external_tool.rules(),
            *source_files.rules(),
            *target_types_rules(),
            QueryRule(Partitions, [ShellcheckRequest.PartitionRequest]),
            QueryRule(LintResult, [ShellcheckRequest.Batch]),
        ],
        target_types=[ShellSourcesGeneratorTarget],
    )


GOOD_FILE = "# shellcheck shell=bash\necho 'shell known'\n"
BAD_FILE = "echo 'shell unknown'\n"


def run_shellcheck(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.shell.lint.shellcheck", *(extra_args or ())],
        env_inherit={"PATH"},
    )
    partitions = rule_runner.request(
        Partitions[ShellcheckFieldSet, Any],
        [
            ShellcheckRequest.PartitionRequest(
                tuple(ShellcheckFieldSet.create(tgt) for tgt in targets)
            )
        ],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [ShellcheckRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_shellcheck(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert not result[0].stdout
    assert not result[0].stderr


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": GOOD_FILE, "BUILD": "shell_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    assert_success(rule_runner, tgt)


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": BAD_FILE, "BUILD": "shell_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    result = run_shellcheck(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "In f.sh line 1:" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.sh": GOOD_FILE, "bad.sh": BAD_FILE, "BUILD": "shell_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.sh")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.sh")),
    ]
    result = run_shellcheck(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "good.sh" not in result[0].stdout
    assert "In bad.sh line 1:" in result[0].stdout


def test_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "a/f.sh": BAD_FILE,
            "a/BUILD": "shell_sources()",
            "a/.shellcheckrc": "disable=SC2148",
            "b/f.sh": BAD_FILE,
            "b/BUILD": "shell_sources()",
        }
    )
    tgts = [
        rule_runner.get_target(Address("a", relative_file_path="f.sh")),
        rule_runner.get_target(Address("b", relative_file_path="f.sh")),
    ]
    result = run_shellcheck(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "a/f.sh" not in result[0].stdout
    assert "In b/f.sh line 1:" in result[0].stdout


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": BAD_FILE, "BUILD": "shell_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    assert_success(rule_runner, tgt, extra_args=["--shellcheck-args=-e SC2148"])


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.sh": BAD_FILE, "BUILD": "shell_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    result = run_shellcheck(rule_runner, [tgt], extra_args=["--shellcheck-skip"])
    assert not result


def test_includes_direct_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "transitive_dep.sh": BAD_FILE,
            "dep.sh": GOOD_FILE,
            "f.sh": "# shellcheck shell=bash\nsource dep.sh\n",
            "BUILD": dedent(
                """\
                shell_sources(name='transitive', sources=['transitive_dep.sh'])
                shell_sources(name='dep', sources=['dep.sh'], dependencies=[':transitive'])
                shell_sources(name='t', sources=['f.sh'], dependencies=[':dep'])
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.sh"))
    assert_success(rule_runner, tgt, extra_args=["--shellcheck-args=--external-sources"])
