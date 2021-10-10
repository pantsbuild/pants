# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.backend.go.util_rules.tests_analysis import (
    AnalyzedTestSources,
    AnalyzeTestSourcesRequest,
    Example,
    TestFunc,
)
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *assembly.rules(),
            *build_pkg.rules(),
            *import_analysis.rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *tests_analysis.rules(),
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

                func Test(t *testing.T) {
                }
                """
            ),
            "bar_test.go": dedent(
                """
                package foo_test

                func BenchmarkThisIsABenchmark(b *testing.B) {
                }

                func Benchmark(b *testing.B) {
                }
                """
            ),
        },
    ).digest

    metadata = rule_runner.request(
        AnalyzedTestSources,
        [
            AnalyzeTestSourcesRequest(
                input_digest, FrozenOrderedSet(["foo_test.go"]), FrozenOrderedSet(["bar_test.go"])
            )
        ],
    )

    assert metadata == AnalyzedTestSources(
        tests=FrozenOrderedSet([TestFunc("TestThisIsATest", "_test"), TestFunc("Test", "_test")]),
        benchmarks=FrozenOrderedSet(
            [TestFunc("BenchmarkThisIsABenchmark", "_xtest"), TestFunc("Benchmark", "_xtest")]
        ),
        examples=FrozenOrderedSet(),
        test_main=None,
    )


def test_collect_examples(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "foo_test.go": dedent(
                """
                package foo
                func ExampleEmptyOutputExpected() {
                    // Output:
                }
                // This does not have an `Output` comment and will be skipped.
                func ExampleEmptyOutputAndNoOutputDirective() {
                }
                func ExampleSomeOutput() {
                    fmt.Println("foo")
                    // Output: foo
                }
                func ExampleAnotherOne() {
                    fmt.Println("foo\\nbar\\n")
                    // Output:
                    // foo
                    // bar
                }
                """
            ),
        },
    ).digest

    metadata = rule_runner.request(
        AnalyzedTestSources,
        [
            AnalyzeTestSourcesRequest(
                input_digest, FrozenOrderedSet(["foo_test.go"]), FrozenOrderedSet()
            )
        ],
    )

    assert metadata == AnalyzedTestSources(
        tests=FrozenOrderedSet(),
        benchmarks=FrozenOrderedSet(),
        examples=FrozenOrderedSet(
            [
                Example(
                    package="_test",
                    name="ExampleAnotherOne",
                    output='"foo\\nbar\\n"',
                    unordered=False,
                ),
                Example(
                    package="_test", name="ExampleEmptyOutputExpected", output='""', unordered=False
                ),
                Example(
                    package="_test", name="ExampleSomeOutput", output='"foo\\n"', unordered=False
                ),
            ]
        ),
        test_main=None,
    )


def test_incorrect_signatures(rule_runner: RuleRunner) -> None:
    test_cases = [
        ("TestFoo(t *testing.T, a int)", "wrong signature for TestFoo"),
        ("TestFoo()", "wrong signature for TestFoo"),
        ("TestFoo(t *testing.B)", "wrong signature for TestFoo"),
        ("TestFoo(t *testing.M)", "wrong signature for TestFoo"),
        ("TestFoo(a int)", "wrong signature for TestFoo"),
        ("BenchmarkFoo(t *testing.B, a int)", "wrong signature for BenchmarkFoo"),
        ("BenchmarkFoo()", "wrong signature for BenchmarkFoo"),
        ("BenchmarkFoo(t *testing.T)", "wrong signature for BenchmarkFoo"),
        ("BenchmarkFoo(t *testing.M)", "wrong signature for BenchmarkFoo"),
        ("BenchmarkFoo(a int)", "wrong signature for BenchmarkFoo"),
    ]

    for test_sig, err_msg in test_cases:
        input_digest = rule_runner.make_snapshot(
            {
                "foo_test.go": dedent(
                    f"""
                    package foo
                    func {test_sig} {{
                    }}
                    """
                ),
            },
        ).digest

        with pytest.raises(ExecutionError) as exc_info:
            rule_runner.request(
                AnalyzedTestSources,
                [
                    AnalyzeTestSourcesRequest(
                        input_digest, FrozenOrderedSet(["foo_test.go"]), FrozenOrderedSet()
                    )
                ],
            )
        assert "" in str(exc_info.value)


def test_duplicate_test_mains_same_file(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "foo_test.go": dedent(
                """
                package foo

                func TestMain(m *testing.M) {
                }

                func TestMain(m *testing.M) {
                }
                """
            ),
        },
    ).digest

    with pytest.raises(ExecutionError) as exc_info:
        rule_runner.request(
            AnalyzedTestSources,
            [
                AnalyzeTestSourcesRequest(
                    input_digest,
                    FrozenOrderedSet(["foo_test.go", "bar_test.go"]),
                    FrozenOrderedSet(),
                )
            ],
        )

    assert "multiple definitions of TestMain" in str(exc_info.value)


def test_duplicate_test_mains_different_files(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "foo_test.go": dedent(
                """
                package foo

                func TestMain(m *testing.M) {
                }
                """
            ),
            "bar_test.go": dedent(
                """
                package foo

                func TestMain(m *testing.M) {
                }
                """
            ),
        },
    ).digest

    with pytest.raises(ExecutionError) as exc_info:
        rule_runner.request(
            AnalyzedTestSources,
            [
                AnalyzeTestSourcesRequest(
                    input_digest,
                    FrozenOrderedSet(["foo_test.go", "bar_test.go"]),
                    FrozenOrderedSet(),
                )
            ],
        )

    assert "multiple definitions of TestMain" in str(exc_info.value)
