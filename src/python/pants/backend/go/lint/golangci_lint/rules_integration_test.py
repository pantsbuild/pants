# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.lint.golangci_lint import skip_field
from pants.backend.go.lint.golangci_lint.rules import GolangciLintFieldSet, GolangciLintRequest
from pants.backend.go.lint.golangci_lint.rules import rules as golangci_lint_rules
from pants.backend.go.lint.golangci_lint.subsystem import GolangciLint
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, external_tool, source_files, system_binaries
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.addresses import Address
from pants.engine.fs import rules as fs_rules
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[GoModTarget, GoPackageTarget],
        rules=[
            *assembly.rules(),
            *build_pkg.rules(),
            *config_files.rules(),
            *external_tool.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *golangci_lint_rules(),
            *import_analysis.rules(),
            *link.rules(),
            *sdk.rules(),
            *skip_field.rules(),
            *source_files.rules(),
            *system_binaries.rules(),
            *target_type_rules.rules(),
            *third_party_pkg.rules(),
            *fs_rules(),
            *archive_rules(),
            QueryRule(Partitions, [GolangciLintRequest.PartitionRequest]),
            QueryRule(LintResult, [GolangciLintRequest.Batch]),
            *GolangciLint.rules(),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


GOOD_FILE = dedent(
    """\
    package main
    import "fmt"
    func main() {
    \ts := "Hello World"
    \tfmt.Printf("%s", s)
    }
    """
)

BAD_FILE = dedent(
    """\
    package grok
    import "fmt"
    func good() {
    \ts := "Hello World"
    \tfmt.Printf("%s", s)
    }
    """
)

GO_MOD = dedent(
    """\
    module example.com/lint
    go 1.17
    """
)


def run_golangci_lint(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> tuple[LintResult, ...]:
    args = extra_args or []
    rule_runner.set_options(args, env_inherit={"PATH"})
    partitions = rule_runner.request(
        Partitions[GolangciLintFieldSet, Any],
        [
            GolangciLintRequest.PartitionRequest(
                tuple(GolangciLintFieldSet.create(tgt) for tgt in targets)
            )
        ],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult, [GolangciLintRequest.Batch("", partition.elements, partition.metadata)]
        )
        results.append(result)
    return tuple(results)


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.go": GOOD_FILE,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
        },
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    lint_results = run_golangci_lint(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.go": BAD_FILE,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    lint_results = run_golangci_lint(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "f.go:3:6: func `good` is unused (unused)\n" in lint_results[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\n",
            "good/BUILD": "go_package()\n",
            "good/f.go": GOOD_FILE,
            "bad/BUILD": "go_package()\n",
            "bad/f.go": BAD_FILE,
        }
    )
    tgts = [
        rule_runner.get_target(Address("good", target_name="good")),
        rule_runner.get_target(Address("bad", target_name="bad")),
    ]
    lint_results = run_golangci_lint(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad/f.go:3:6: func `good` is unused (unused)\n" in lint_results[0].stdout
    assert "good/f.go" not in lint_results[0].stdout


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.go": BAD_FILE,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    lint_results = run_golangci_lint(rule_runner, [tgt], extra_args=["--golangci-lint-skip"])
    assert not lint_results
