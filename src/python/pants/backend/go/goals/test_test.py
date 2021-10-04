# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import pytest

from pants.backend.go.goals.test import GoTestFieldSet
from pants.backend.go.goals.test import rules as test_rules
from pants.backend.go.target_types import GoModTarget, GoPackage
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *test_rules(),
            QueryRule(TestResult, [GoTestFieldSet]),
        ],
        target_types=[GoPackage, GoModTarget],
    )
    return rule_runner


def test_stub_is_a_stub(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod()\ngo_package(name='lib')\n",
            "foo/go.mod": "module foo\n",
            "foo/go.sum": "",
            "foo/bar_test.go": "package foo\n",
        }
    )

    with pytest.raises(ExecutionError) as exc_info:
        tgt = rule_runner.get_target(Address("foo", target_name="lib"))
        rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])

    assert "NotImplementedError: This is a stub." in str(exc_info.value)
