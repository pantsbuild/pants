# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go.util_rules import compile, import_analysis, link, sdk, tests_analysis
from pants.backend.go.util_rules.tests_analysis import (
    AnalyzedTestSources,
    AnalyzeTestSourcesRequest,
    GoTestCase,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *tests_analysis.rules(),
            *import_analysis.rules(),
            *compile.rules(),
            *link.rules(),
            *sdk.rules(),
            QueryRule(AnalyzedTestSources, [AnalyzeTestSourcesRequest]),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_basic_test_analysis(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "foo_test.go": dedent(
                """
                package foo

                func TestThisIsATest(t *testing.T) {
                }

                func TestNotATest() {
                }

                func Test(t *testing.T) {
                }
                """
            )
        },
    ).digest

    metadata = rule_runner.request(
        AnalyzedTestSources,
        [AnalyzeTestSourcesRequest(input_digest, FrozenOrderedSet(["foo_test.go"]))],
    )

    assert metadata == AnalyzedTestSources(
        tests=FrozenOrderedSet([GoTestCase("TestThisIsATest", "foo"), GoTestCase("Test", "foo")]),
        benchmarks=FrozenOrderedSet(),
        has_test_main=False,
    )
