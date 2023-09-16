# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.test import GoTestFieldSet, GoTestRequest
from pants.backend.go.goals.test import rules as test_rules
from pants.backend.go.target_types import GoBinaryTarget, GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    implicit_linker_deps,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult, get_filtered_environment
from pants.core.util_rules import source_files
from pants.engine.process import ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


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
            *implicit_linker_deps.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *tests_analysis.rules(),
            *third_party_pkg.rules(),
            *source_files.rules(),
            get_filtered_environment,
            QueryRule(TestResult, (GoTestRequest.Batch,)),
            QueryRule(ProcessResult, (GoSdkProcess,)),
        ],
        target_types=[GoModTarget, GoPackageTarget, GoBinaryTarget],
    )
    rule_runner.set_options(["--go-test-args=-v"], env_inherit={"PATH"})
    return rule_runner


def test_multiple_go_mod_support(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": dedent(
                """\
            go_mod(name="mod")
            go_package()
            """
            ),
            "foo/go.mod": "module foo",
            "foo/add.go": dedent(
                """\
            package foo
            func add(x, y int) int {
              return x + y
            }
            """
            ),
            "foo/add_test.go": dedent(
                """\
            package foo
            import "testing"
            func TestFoo(t *testing.T) {
              if add(2, 3) != 5 {
                t.Fail()
              }
            }
            """
            ),
            "bar/BUILD": dedent(
                """\
            go_mod(name="mod")
            go_package()
            """
            ),
            "bar/go.mod": "module bar",
            "bar/add.go": dedent(
                """\
            package bar
            func add(x, y int) int {
              return x + y
            }
            """
            ),
            "bar/add_test.go": dedent(
                """\
            package bar
            import "testing"
            func TestBar(t *testing.T) {
              if add(2, 3) != 5 {
                t.Fail()
              }
            }
            """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(
        TestResult, [GoTestRequest.Batch("", (GoTestFieldSet.create(tgt),), None)]
    )
    assert result.exit_code == 0
    assert b"PASS: TestFoo" in result.stdout_bytes

    tgt = rule_runner.get_target(Address("bar"))
    result = rule_runner.request(
        TestResult, [GoTestRequest.Batch("", (GoTestFieldSet.create(tgt),), None)]
    )
    assert result.exit_code == 0
    assert b"PASS: TestBar" in result.stdout_bytes
