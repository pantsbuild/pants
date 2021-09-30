# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap

import pytest

from pants.backend.go.util_rules import compile, import_analysis, link, sdk, test_analysis
from pants.backend.go.util_rules.test_analysis import (
    AnalyzedTestSources,
    AnalyzeTestSourcesRequest,
    GoTestCase,
)
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *test_analysis.rules(),
            *import_analysis.rules(),
            *compile.rules(),
            *link.rules(),
            *sdk.rules(),
            # *source_files.rules(),
            QueryRule(AnalyzedTestSources, [AnalyzeTestSourcesRequest]),
            QueryRule(Digest, [CreateDigest]),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def make_digest(rule_runner: RuleRunner, data: dict[str, str]) -> Digest:
    file_contents = [FileContent(path=k, content=v.encode("utf-8")) for k, v in data.items()]
    return rule_runner.request(Digest, [CreateDigest(file_contents)])


def test_basic_test_analysis(rule_runner: RuleRunner) -> None:
    input_digest = make_digest(
        rule_runner,
        {
            "foo_test.go": textwrap.dedent(
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
    )

    metadata = rule_runner.request(
        AnalyzedTestSources,
        [
            AnalyzeTestSourcesRequest(
                digest=input_digest,
                paths=FrozenOrderedSet(["foo_test.go"]),
            )
        ],
    )

    assert metadata == AnalyzedTestSources(
        tests=FrozenOrderedSet([GoTestCase("TestThisIsATest", "foo"), GoTestCase("Test", "foo")]),
        benchmarks=FrozenOrderedSet(),
        has_test_main=False,
    )
