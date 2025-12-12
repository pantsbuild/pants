# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.lint.golangci_lint import skip_field
from pants.backend.go.lint.golangci_lint.rules import (
    GolangciLintFieldSet,
    GolangciLintPartitionMetadata,
    GolangciLintRequest,
)
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
from pants.engine.addresses import Address
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
        Partitions[GolangciLintFieldSet, GolangciLintPartitionMetadata],
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


@pytest.mark.platform_specific_behavior
def test_passing_v1(rule_runner: RuleRunner) -> None:
    """Test backwards compatibility with golangci-lint v1."""
    rule_runner.write_files(
        {
            "f.go": GOOD_FILE,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
        },
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    # Explicitly use v1 to verify backwards compatibility
    lint_results = run_golangci_lint(
        rule_runner, [tgt], extra_args=["--golangci-lint-version=1.64.6"]
    )
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""


@pytest.mark.platform_specific_behavior
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
    # Check for unused function error (format varies between v1 and v2)
    assert "f.go:3:6:" in lint_results[0].stdout
    assert "is unused (unused)" in lint_results[0].stdout


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
    # Check for unused function error (format varies between v1 and v2)
    assert "bad/f.go:3:6:" in lint_results[0].stdout
    assert "is unused (unused)" in lint_results[0].stdout
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


@pytest.mark.platform_specific_behavior
def test_multiple_go_mods(rule_runner: RuleRunner) -> None:
    """Test linting across multiple go.mod files (multiple modules)."""
    rule_runner.write_files(
        {
            # Module A - should pass
            "mod_a/go.mod": dedent(
                """\
                module example.com/mod_a
                go 1.21
                """
            ),
            "mod_a/BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
            "mod_a/main.go": GOOD_FILE,
            # Module B - should fail (unused function)
            "mod_b/go.mod": dedent(
                """\
                module example.com/mod_b
                go 1.21
                """
            ),
            "mod_b/BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
            "mod_b/bad.go": BAD_FILE,
        }
    )
    tgts = [
        rule_runner.get_target(Address("mod_a", target_name="pkg")),
        rule_runner.get_target(Address("mod_b", target_name="pkg")),
    ]
    lint_results = run_golangci_lint(rule_runner, tgts)
    # Should get 2 partitions (one per module)
    assert len(lint_results) == 2

    # Find results by module
    results_by_exit_code = {r.exit_code: r for r in lint_results}
    assert 0 in results_by_exit_code, "mod_a should pass"
    assert 1 in results_by_exit_code, "mod_b should fail"

    # Verify the failure is in mod_b
    failing_result = results_by_exit_code[1]
    assert "bad.go" in failing_result.stdout or "bad.go" in failing_result.stderr
