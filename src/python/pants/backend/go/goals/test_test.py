# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.test import GoTestFieldSet
from pants.backend.go.goals.test import rules as test_rules
from pants.backend.go.target_types import GoModTarget
from pants.backend.go.util_rules import external_pkg, first_party_pkg, go_mod, sdk
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *test_rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *external_pkg.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            QueryRule(TestResult, [GoTestFieldSet]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_stub_is_a_stub(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod()",
            "foo/go.mod": "module foo",
            "foo/bar_test.go": "package foo",
        }
    )
    tgt = rule_runner.get_target(Address("foo", generated_name="./"))
    with engine_error(NotImplementedError):
        rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
