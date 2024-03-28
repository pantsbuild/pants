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
from pants.backend.go.util_rules.tests_analysis import GeneratedTestMain, GenerateTestMainRequest
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.fs import rules as fs_rules
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
            *fs_rules(),
            *archive_rules(),
            QueryRule(GeneratedTestMain, [GenerateTestMainRequest]),
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
        GeneratedTestMain,
        [
            GenerateTestMainRequest(
                digest=input_digest,
                test_paths=FrozenOrderedSet(["foo_test.go"]),
                xtest_paths=FrozenOrderedSet(["bar_test.go"]),
                import_path="foo",
                register_cover=False,
                address=Address("foo"),
            )
        ],
    )

    assert metadata.digest != EMPTY_DIGEST
    assert metadata.has_tests
    assert metadata.has_xtests


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
        GeneratedTestMain,
        [
            GenerateTestMainRequest(
                digest=input_digest,
                test_paths=FrozenOrderedSet(["foo_test.go"]),
                xtest_paths=FrozenOrderedSet(),
                import_path="foo",
                register_cover=False,
                address=Address("foo"),
            )
        ],
    )

    assert metadata.digest != EMPTY_DIGEST
    assert metadata.has_tests
    assert not metadata.has_xtests


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

        result = rule_runner.request(
            GeneratedTestMain,
            [
                GenerateTestMainRequest(
                    digest=input_digest,
                    test_paths=FrozenOrderedSet(["foo_test.go"]),
                    xtest_paths=FrozenOrderedSet(),
                    import_path="foo",
                    register_cover=False,
                    address=Address("foo"),
                )
            ],
        )
        assert result.failed_exit_code_and_stderr is not None
        exit_code, stderr = result.failed_exit_code_and_stderr
        assert exit_code == 1
        assert err_msg in stderr


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

    result = rule_runner.request(
        GeneratedTestMain,
        [
            GenerateTestMainRequest(
                digest=input_digest,
                test_paths=FrozenOrderedSet(["foo_test.go", "bar_test.go"]),
                xtest_paths=FrozenOrderedSet(),
                import_path="foo",
                register_cover=False,
                address=Address("foo"),
            )
        ],
    )
    assert result.failed_exit_code_and_stderr is not None
    exit_code, stderr = result.failed_exit_code_and_stderr
    assert exit_code == 1
    assert "multiple definitions of TestMain" in stderr


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

    result = rule_runner.request(
        GeneratedTestMain,
        [
            GenerateTestMainRequest(
                digest=input_digest,
                test_paths=FrozenOrderedSet(["foo_test.go", "bar_test.go"]),
                xtest_paths=FrozenOrderedSet(),
                import_path="foo",
                register_cover=False,
                address=Address("foo"),
            )
        ],
    )
    assert result.failed_exit_code_and_stderr is not None
    exit_code, stderr = result.failed_exit_code_and_stderr
    assert exit_code == 1
    assert "multiple definitions of TestMain" in stderr
