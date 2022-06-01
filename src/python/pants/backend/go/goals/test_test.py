# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.test import GoTestFieldSet
from pants.backend.go.goals.test import rules as test_rules
from pants.backend.go.goals.test import transform_test_args
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
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.core.goals.test import TestResult
from pants.core.target_types import FileTarget
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.process import ProcessResult
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
            QueryRule(ProcessResult, [GoSdkProcess]),
        ],
        target_types=[GoModTarget, GoPackageTarget, FileTarget],
    )
    rule_runner.set_options(["--go-test-args=-v -bench=."], env_inherit={"PATH"})
    return rule_runner


def test_transform_test_args() -> None:
    assert transform_test_args(["-v", "--", "-v"], timeout_field_value=None) == (
        "-test.v",
        "--",
        "-v",
    )
    assert transform_test_args(["-run=TestFoo", "-v"], timeout_field_value=None) == (
        "-test.run=TestFoo",
        "-test.v",
    )
    assert transform_test_args(["-run", "TestFoo", "-foo", "-v"], timeout_field_value=None) == (
        "-test.run",
        "TestFoo",
        "-foo",
        "-test.v",
    )

    assert transform_test_args(["-timeout=1m", "-v"], timeout_field_value=None) == (
        "-test.timeout=1m",
        "-test.v",
    )
    assert transform_test_args(["-timeout", "1m", "-v"], timeout_field_value=None) == (
        "-test.timeout",
        "1m",
        "-test.v",
    )
    assert transform_test_args(["-v"], timeout_field_value=100) == ("-test.v", "-test.timeout=100s")
    assert transform_test_args(["-timeout=1m", "-v"], timeout_field_value=100) == (
        "-test.timeout=1m",
        "-test.v",
    )
    assert transform_test_args(["-timeout", "1m", "-v"], timeout_field_value=100) == (
        "-test.timeout",
        "1m",
        "-test.v",
    )


def test_internal_test_success(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """
                package foo
                func add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """
                package foo
                import "testing"
                func TestAdd(t *testing.T) {
                  if add(2, 3) != 5 {
                    t.Fail()
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "PASS: TestAdd" in result.stdout


def test_internal_test_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/bar_test.go": textwrap.dedent(
                """
                package foo
                import "testing"
                func TestAdd(t *testing.T) {
                  t.Fail()
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 1
    assert "FAIL: TestAdd" in result.stdout


def test_internal_benchmark_passes(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/fib.go": textwrap.dedent(
                """
                package foo
                func Fib(n int) int {
                  if n < 2 {
                    return n
                  }
                  return Fib(n-1) + Fib(n-2)
                }
                """
            ),
            "foo/fib_test.go": textwrap.dedent(
                """
                package foo
                import "testing"
                func BenchmarkAdd(b *testing.B) {
                  for n := 0; n < b.N; n++ {
                    Fib(10)
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "BenchmarkAdd" in result.stdout
    assert "PASS" in result.stdout


def test_internal_example_passes(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/print_test.go": textwrap.dedent(
                """
                package foo
                import (
                  "fmt"
                )
                func ExamplePrint() {
                  fmt.Println("foo")
                  // Output: foo
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "PASS: ExamplePrint" in result.stdout


def test_internal_test_with_test_main(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add_test.go": textwrap.dedent(
                """
                package foo
                import (
                  "fmt"
                  "testing"
                )
                func TestAdd(t *testing.T) {
                  t.Fail()
                }
                func TestMain(m *testing.M) {
                  fmt.Println("foo.TestMain called")
                  m.Run()
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 1
    assert "foo.TestMain called" in result.stdout
    assert "FAIL: TestAdd" in result.stdout


def test_internal_test_fails_to_compile(rule_runner: RuleRunner) -> None:
    """A compilation failure should not cause Pants to error, only the test to fail."""
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            # Test itself is bad.
            "foo/bad_test.go": "invalid!!!",
            # A dependency of the test is bad.
            "foo/dep/f.go": "invalid!!!",
            "foo/dep/BUILD": "go_package()",
            "foo/uses_dep/BUILD": "go_package()",
            "foo/uses_dep/f_test.go": textwrap.dedent(
                """
                package uses_dep

                import (
                  "foo/dep"
                  "testing"
                )

                func TestAdd(t *testing.T) {
                  if add(2, 3) != 5 {
                    t.Fail()
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 1
    assert "bad_test.go:1:1: expected 'package', found invalid\n" in result.stderr

    tgt = rule_runner.get_target(Address("foo/uses_dep"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 1
    assert "dep/f.go:1:1: expected 'package', found invalid\n" in result.stderr


def test_external_test_success(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """
                package foo
                func Add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """
                package foo_test
                import (
                  "foo"
                  "testing"
                )
                func TestAdd(t *testing.T) {
                  if foo.Add(2, 3) != 5 {
                    t.Fail()
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "PASS: TestAdd" in result.stdout


def test_external_test_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """
                package foo
                func Add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """
                package foo_test
                import (
                  _ "foo"
                  "testing"
                )
                func TestAdd(t *testing.T) {
                  t.Fail()
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo", generated_name="./"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 1
    assert "FAIL: TestAdd" in result.stdout


def test_external_benchmark_passes(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/fib.go": textwrap.dedent(
                """
                package foo
                func Fib(n int) int {
                  if n < 2 {
                    return n
                  }
                  return Fib(n-1) + Fib(n-2)
                }
                """
            ),
            "foo/fib_test.go": textwrap.dedent(
                """
                package foo_test
                import (
                  "foo"
                  "testing"
                )
                func BenchmarkAdd(b *testing.B) {
                  for n := 0; n < b.N; n++ {
                    foo.Fib(10)
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "BenchmarkAdd" in result.stdout
    assert "PASS" in result.stdout


def test_external_example_passes(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/print.go": textwrap.dedent(
                """
                package foo
                import "fmt"
                func MyPrint(msg string) {
                  fmt.Println(msg)
                }
                """
            ),
            "foo/print_test.go": textwrap.dedent(
                """
                package foo_test
                import (
                  "foo"
                )
                func ExamplePrint() {
                  foo.MyPrint("foo")
                  // Output: foo
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "PASS: ExamplePrint" in result.stdout


def test_external_test_with_test_main(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """
                package foo
                func Add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """
                package foo_test
                import (
                  "foo"
                  "fmt"
                  "testing"
                )
                func TestAdd(t *testing.T) {
                  if foo.Add(2, 3) != 5 {
                    t.Fail()
                  }
                }
                func TestMain(m *testing.M) {
                  fmt.Println("foo_test.TestMain called")
                  m.Run()
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo", generated_name="./"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "foo_test.TestMain called" in result.stdout


def test_both_internal_and_external_tests_fail(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """
                package foo
                func Add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_int_test.go": textwrap.dedent(
                """
                package foo
                import (
                  "testing"
                )
                func TestAddInternal(t *testing.T) {
                  t.Fail()
                }
                """
            ),
            "foo/add_ext_test.go": textwrap.dedent(
                """
                package foo_test
                import (
                  _ "foo"
                  "testing"
                )
                func TestAddExternal(t *testing.T) {
                  t.Fail()
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 1
    assert "FAIL: TestAddInternal" in result.stdout
    assert "FAIL: TestAddExternal" in result.stdout


@pytest.mark.no_error_if_skipped
def test_fuzz_target_supported(rule_runner: RuleRunner) -> None:
    go_version_result = rule_runner.request(
        ProcessResult, [GoSdkProcess(["version"], description="Get `go` version.")]
    )
    if "go1.18" not in go_version_result.stdout.decode():
        pytest.skip("Skipping because Go SDK is not 1.18 or higher.")

    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/fuzz_test.go": textwrap.dedent(
                """
                package foo
                import (
                  "testing"
                )
                func FuzzFoo(f *testing.F) {
                  f.Add("foo")
                  f.Fuzz(func(t *testing.T, v string) {
                    if v != "foo" {
                      t.Fail()
                    }
                  })
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "PASS: FuzzFoo" in result.stdout


def test_skip_tests(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f_test.go": "",
            "BUILD": textwrap.dedent(
                """\
                go_package(name='run')
                go_package(name='skip', skip_tests=True)
                """
            ),
        }
    )

    def is_applicable(tgt_name: str) -> bool:
        tgt = rule_runner.get_target(Address("", target_name=tgt_name))
        return GoTestFieldSet.is_applicable(tgt)

    assert is_applicable("run")
    assert not is_applicable("skip")


def test_no_tests(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """
                package foo
                func add(x, y int) int {
                  return x + y
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.skipped


def test_compilation_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """
                package foo
                func add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """
                package foo
                import "testing"
                !!!
                func TestAdd(t *testing.T) {
                  if add(2, 3) != 5 {
                    t.Fail()
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 1
    assert "failed to parse" in result.stderr


def test_file_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.txt": "",
            "BUILD": "file(name='root', source='f.txt')",
            "foo/BUILD": textwrap.dedent(
                """
                go_mod(name='mod')
                go_package(dependencies=[":testdata", "//:root"])
                file(name="testdata", source="testdata/f.txt")
                """
            ),
            "foo/go.mod": "module foo",
            "foo/foo_test.go": textwrap.dedent(
                """
                package foo
                import (
                  "os"
                  "testing"
                )

                func TestFilesAvailable(t *testing.T) {
                  _, err1 := os.Stat("testdata/f.txt")
                  if err1 != nil {
                    t.Fatalf("Could not stat foo/testdata/f.txt: %v", err1)
                  }
                  _, err2 := os.Stat("../f.txt")
                  if err2 != nil {
                    t.Fatalf("Could not stat f.txt: %v", err2)
                  }
                }
                """
            ),
            "foo/testdata/f.txt": "",
        }
    )
    tgt = rule_runner.get_target(Address("foo"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
