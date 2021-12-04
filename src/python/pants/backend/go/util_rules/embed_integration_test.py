# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.test import GoTestFieldSet
from pants.backend.go.goals.test import rules as test_rules
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult
from pants.core.target_types import ResourceTarget
from pants.core.util_rules import source_files
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *test_rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *link.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *tests_analysis.rules(),
            *third_party_pkg.rules(),
            *source_files.rules(),
            QueryRule(TestResult, [GoTestFieldSet]),
        ],
        target_types=[GoModTarget, GoPackageTarget, ResourceTarget],
    )
    rule_runner.set_options(["--go-test-args=-v -bench=."], env_inherit={"PATH"})
    return rule_runner


def test_embeds_integration_test(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                go_mod(name='mod')
                go_package(name='pkg', dependencies=[":grok", ":test_grok", ":xtest_grok"])
                resource(name='grok', source='grok.txt')
                resource(name='test_grok', source='test_grok.txt')
                resource(name='xtest_grok', source='xtest_grok.txt')
                """
            ),
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "grok.txt": "hello",
            "test_grok.txt": "world",
            "xtest_grok.txt": "xtest",
            "foo.go": dedent(
                """\
                package foo
                import _ "embed"
                //go:embed grok.txt
                var message string
                """
            ),
            "foo_test.go": dedent(
                """\
                package foo
                import (
                  _ "embed"
                  "testing"
                )
                //go:embed test_grok.txt
                var testMessage string

                func TestFoo(t *testing.T) {
                  if message != "hello" {
                    t.Fatalf("message mismatch: want=%s; got=%s", "hello", message)
                  }
                  if testMessage != "world" {
                    t.Fatalf("testMessage mismatch: want=%s; got=%s", "world", testMessage)
                  }
                }
                """
            ),
            "bar_test.go": dedent(
                """\
                package foo_test
                import (
                  _ "embed"
                  "testing"
                )
                //go:embed xtest_grok.txt
                var testMessage string

                func TestBar(t *testing.T) {
                  if testMessage != "xtest" {
                    t.Fatalf("testMessage mismatch: want=%s; got=%s", "xtest", testMessage)
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
