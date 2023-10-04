# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import check
from pants.backend.go.goals.check import GoCheckFieldSet, GoCheckRequest
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.core.goals.check import CheckResult, CheckResults
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *check.rules(),
            *sdk.rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *import_analysis.rules(),
            *link.rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *target_type_rules.rules(),
            QueryRule(CheckResults, [GoCheckRequest]),
        ],
        target_types=[GoModTarget, GoPackageTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_check(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/greeter
                go 1.17
                """
            ),
            "BUILD": "go_mod(name='mod')",
            "bad/f.go": "invalid!!!",
            "bad/BUILD": "go_package()",
            "good/f.go": dedent(
                """\
                package greeter

                import "fmt"

                func Hello() {
                    fmt.Println("Hello world!")
                }
                """
            ),
            "good/BUILD": "go_package()",
        }
    )
    targets = [rule_runner.get_target(Address("bad")), rule_runner.get_target(Address("good"))]
    results = rule_runner.request(
        CheckResults, [GoCheckRequest(GoCheckFieldSet.create(tgt) for tgt in targets)]
    ).results
    assert set(results) == {CheckResult(1, "", "")}
