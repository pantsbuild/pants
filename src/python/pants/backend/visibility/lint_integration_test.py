# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.visibility.lint import EnforceVisibilityRules, VisibilityFieldSet
from pants.backend.visibility.lint import rules as lint_rules
from pants.backend.visibility.rules import rules as visibility_rules
from pants.core.goals.lint import Lint, LintResult
from pants.core.target_types import GenericTarget
from pants.core.util_rules.partitions import _EmptyMetadata
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *lint_rules(),
            *visibility_rules(),
            QueryRule(LintResult, (EnforceVisibilityRules.Batch,)),
        ],
        target_types=[GenericTarget],
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                __dependencies_rules__(
                    # No dependencies at all allowed
                    ("*", "!*"),
                )

                target(name="root")
                target(name="leaf", dependencies=["//:root"])

                """
            ),
        }
    )
    return rule_runner


def run_lint(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> LintResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.experimental.visibilty", *(extra_args or ())],
    )
    field_sets = [VisibilityFieldSet.create(tgt) for tgt in targets]
    with rule_runner.scheduler._goals._execute(Lint):
        lint_result = rule_runner.request(
            LintResult,
            [
                EnforceVisibilityRules.Batch(
                    "",
                    tuple(field_sets),
                    partition_metadata=_EmptyMetadata(),
                ),
            ],
        )
    return lint_result


def test_lint_success(rule_runner: RuleRunner) -> None:
    tgt = rule_runner.get_target(Address("", target_name="root"))
    lint_result = run_lint(
        rule_runner,
        [tgt],
    )
    assert lint_result.exit_code == 0
    assert lint_result.stderr == ""
    assert lint_result.stdout == ""


def test_lint_failure(rule_runner: RuleRunner) -> None:
    tgt = rule_runner.get_target(Address("", target_name="leaf"))
    lint_result = run_lint(
        rule_runner,
        [tgt],
    )
    assert lint_result.exit_code == 1
    assert lint_result.stderr == ""
    assert (
        lint_result.stdout
        == dedent(
            """\
            //:leaf has 1 dependency violation:

              * BUILD[!*] -> : DENY
                target //:leaf -> target //:root
            """
        ).strip()
    )
