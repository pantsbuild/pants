# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import textwrap

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.test import GoTestFieldSet, GoTestRequest
from pants.backend.go.goals.test import rules as test_rules
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    coverage,
    coverage_output,
    first_party_pkg,
    go_mod,
    implicit_linker_deps,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.backend.go.util_rules.coverage import GoCoverageData, registers_coverage_via_testdeps
from pants.backend.go.util_rules.coverage_output import GoCoverageDataCollection
from pants.backend.go.util_rules.goroot import GoRoot
from pants.build_graph.address import Address
from pants.core.goals.test import (
    CoverageReport,
    CoverageReports,
    FilesystemCoverageReport,
    TestResult,
    get_filtered_environment,
)
from pants.core.target_types import FileTarget
from pants.core.util_rules import source_files
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import Digest
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner(go_binary_path: str) -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *test_rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *coverage.rules(),
            *coverage_output.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            # NB: required for `runtime/race`, which only reaches the linker as an implicit dep.
            *implicit_linker_deps.rules(),
            *link.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *tests_analysis.rules(),
            *third_party_pkg.rules(),
            *source_files.rules(),
            get_filtered_environment,
            QueryRule(TestResult, (GoTestRequest.Batch,)),
            QueryRule(CoverageReports, (GoCoverageDataCollection,)),
            QueryRule(DigestContents, (Digest,)),
            QueryRule(GoRoot, ()),
        ],
        target_types=[GoModTarget, GoPackageTarget, FileTarget],
    )

    # Configure Pants to use the specific Go binary.
    go_binary_dir = os.path.dirname(go_binary_path)
    rule_runner.set_options(
        [
            "--go-test-args=-v -bench=.",
            "--test-use-coverage",
            f"--golang-go-search-paths=[{repr(go_binary_dir)}]",
        ],
        env_inherit={"PATH"},
    )
    return rule_runner


def test_basic_coverage(rule_runner: RuleRunner) -> None:
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
    result = rule_runner.request(
        TestResult, [GoTestRequest.Batch("", (GoTestFieldSet.create(tgt),), None)]
    )
    assert result.exit_code == 0
    assert b"PASS: TestAdd" in result.stdout_bytes
    coverage_data = result.coverage_data
    assert coverage_data is not None
    assert isinstance(coverage_data, GoCoverageData)
    assert coverage_data.import_path == "foo"
    coverage_reports = rule_runner.request(
        CoverageReports, [GoCoverageDataCollection([coverage_data])]
    )
    assert len(coverage_reports.reports) == 2
    reports: list[CoverageReport] = list(coverage_reports.reports)

    go_report = reports[0]
    assert isinstance(go_report, FilesystemCoverageReport)
    digest_contents = rule_runner.request(DigestContents, (go_report.result_snapshot.digest,))
    assert len(digest_contents) == 1
    assert digest_contents[0].path == "cover.out"

    html_report = reports[1]
    assert isinstance(html_report, FilesystemCoverageReport)
    digest_contents = rule_runner.request(DigestContents, (html_report.result_snapshot.digest,))
    assert len(digest_contents) == 1
    assert digest_contents[0].path == "coverage.html"


def test_coverage_of_multiple_packages(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            # `foo/adder` is a separate package so the test can attempt to include it into coverage of the
            # `foo` package.
            "foo/adder/BUILD": "go_package()",
            "foo/adder/add.go": textwrap.dedent(
                """\
            package adder
            func Add(x, y int) int {
              return x + y
            }
            """
            ),
            "foo/add.go": textwrap.dedent(
                """\
                package foo
                import "foo/adder"
                func add(x, y int) int {
                  return adder.Add(x, y)
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """\
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

    def run_test(tgt: Target) -> str:
        result = rule_runner.request(
            TestResult, [GoTestRequest.Batch("", (GoTestFieldSet.create(tgt),), None)]
        )
        assert result.exit_code == 0
        assert b"PASS: TestAdd" in result.stdout_bytes
        coverage_data = result.coverage_data
        assert coverage_data is not None
        assert isinstance(coverage_data, GoCoverageData)
        assert coverage_data.import_path == "foo"
        coverage_reports = rule_runner.request(
            CoverageReports, [GoCoverageDataCollection([coverage_data])]
        )
        assert len(coverage_reports.reports) == 2
        reports: list[CoverageReport] = list(coverage_reports.reports)

        go_report = reports[0]
        assert isinstance(go_report, FilesystemCoverageReport)
        digest_contents = rule_runner.request(DigestContents, (go_report.result_snapshot.digest,))
        assert len(digest_contents) == 1
        assert digest_contents[0].path == "cover.out"

        raw_go_report = digest_contents[0].content.decode()

        html_report = reports[1]
        assert isinstance(html_report, FilesystemCoverageReport)
        digest_contents = rule_runner.request(DigestContents, (html_report.result_snapshot.digest,))
        assert len(digest_contents) == 1
        assert digest_contents[0].path == "coverage.html"

        return raw_go_report

    # Test that the `foo/adder` package is missing when it is **not** configured to be covered
    # via the `--go-test-coverage-include-patterns` option.
    tgt = rule_runner.get_target(Address("foo"))
    cover_report = run_test(tgt)
    assert "foo/add.go" in cover_report
    assert "foo/adder/add.go" not in cover_report

    # Then set `--go-test-coverage-include-patterns` to include the `foo/adder` package in coverage.
    # It should now show up in the raw coverage report.
    rule_runner.set_options(
        [
            "--go-test-args=-v -bench=.",
            "--test-use-coverage",
            "--go-test-coverage-packages=foo/adder",
        ],
        env_inherit={"PATH"},
    )
    multi_cover_report = run_test(tgt)
    assert "foo/add.go" in multi_cover_report
    assert "foo/adder/add.go" in multi_cover_report


def _run_test(rule_runner: RuleRunner, tgt: Target) -> TestResult:
    return rule_runner.request(
        TestResult, [GoTestRequest.Batch("", (GoTestFieldSet.create(tgt),), None)]
    )


def _coverage_profile(rule_runner: RuleRunner, coverage_data: GoCoverageData) -> str:
    """Render the coverage reports and return the raw `cover.out` profile."""
    coverage_reports = rule_runner.request(
        CoverageReports, [GoCoverageDataCollection([coverage_data])]
    )
    go_report = next(
        report
        for report in coverage_reports.reports
        if isinstance(report, FilesystemCoverageReport) and report.report_type == "go_cover"
    )
    digest_contents = rule_runner.request(DigestContents, (go_report.result_snapshot.digest,))
    assert [fc.path for fc in digest_contents] == ["cover.out"]
    return digest_contents[0].content.decode()


def _covered_files(profile: str) -> list[str]:
    """The file names in a profile, in the order in which they first appear."""
    file_names: list[str] = []
    for line in profile.splitlines()[1:]:  # Skip the `mode:` line.
        file_name = line.split(":", 1)[0]
        if file_name not in file_names:
            file_names.append(file_name)
    return file_names


def test_coverage_with_test_main_calling_os_exit(rule_runner: RuleRunner) -> None:
    """A `TestMain` which ends in `os.Exit(m.Run())` must still produce a coverage profile.

    `os.Exit` skips everything after `m.Run()` in the generated test main, so coverage may only be
    written from within `m.Run()` itself.
    """
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """\
                package foo
                func add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """\
                package foo
                import (
                  "os"
                  "testing"
                )
                func TestMain(m *testing.M) {
                  os.Exit(m.Run())
                }
                func TestAdd(t *testing.T) {
                  if add(2, 3) != 5 {
                    t.Fail()
                  }
                }
                """
            ),
        }
    )
    result = _run_test(rule_runner, rule_runner.get_target(Address("foo")))
    assert result.exit_code == 0
    assert result.coverage_data is not None
    assert isinstance(result.coverage_data, GoCoverageData)

    profile = _coverage_profile(rule_runner, result.coverage_data)
    assert profile.startswith("mode: set\n")
    assert _covered_files(profile) == ["foo/add.go"]
    # `add` was called, so its block must have a non-zero execution count.
    counts = [int(line.rsplit(" ", 1)[1]) for line in profile.splitlines()[1:]]
    assert counts == [1]


@pytest.mark.no_error_if_skipped
def test_coverage_profile_is_deterministic(rule_runner: RuleRunner) -> None:
    """The profile is written in sorted file order.

    `cover.out` is materialized to `dist/`, so its contents must not depend on Go's randomized map
    iteration order.
    """
    if not registers_coverage_via_testdeps(rule_runner.request(GoRoot, [])):
        pytest.skip(
            "Go < 1.25 writes the coverage profile itself, by iterating a map, so Pants cannot "
            "make its contents deterministic."
        )

    sources = {
        "foo/BUILD": "go_mod(name='mod')\ngo_package()",
        "foo/go.mod": "module foo",
        "foo/foo_test.go": textwrap.dedent(
            """\
            package foo
            import "testing"
            func TestAll(t *testing.T) {
              if a()+b()+c()+d() != 4 {
                t.Fail()
              }
            }
            """
        ),
    }
    for name in ("a", "b", "c", "d"):
        sources[f"foo/{name}.go"] = textwrap.dedent(
            f"""\
            package foo
            func {name}() int {{
              return 1
            }}
            """
        )
    rule_runner.write_files(sources)

    result = _run_test(rule_runner, rule_runner.get_target(Address("foo")))
    assert result.exit_code == 0
    assert isinstance(result.coverage_data, GoCoverageData)

    covered_files = _covered_files(_coverage_profile(rule_runner, result.coverage_data))
    assert covered_files == [f"foo/{name}.go" for name in ("a", "b", "c", "d")]


def test_missing_coverage_profile_is_not_fatal(rule_runner: RuleRunner) -> None:
    """A test binary which exits without running any tests writes no profile.

    Pants must report that as "no coverage data" rather than crashing on the empty output.
    """
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """\
                package foo
                func add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """\
                package foo
                import (
                  "os"
                  "testing"
                )
                func TestMain(m *testing.M) {
                  os.Exit(0)
                }
                func TestAdd(t *testing.T) {
                  if add(2, 3) != 5 {
                    t.Fail()
                  }
                }
                """
            ),
        }
    )
    result = _run_test(rule_runner, rule_runner.get_target(Address("foo")))
    assert result.exit_code == 0
    assert result.coverage_data is None


def test_coverage_with_other_profiles_enabled(rule_runner: RuleRunner) -> None:
    """Other profiles land in the same output digest and must not be read as the cover profile."""
    rule_runner.set_options(
        [
            "--test-use-coverage",
            "--go-test-block-profile",
        ],
        env_inherit={"PATH"},
    )
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """\
                package foo
                func add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """\
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
    result = _run_test(rule_runner, rule_runner.get_target(Address("foo")))
    assert result.exit_code == 0
    assert result.extra_output is not None
    assert "block.out" in result.extra_output.files
    assert isinstance(result.coverage_data, GoCoverageData)

    profile = _coverage_profile(rule_runner, result.coverage_data)
    assert profile.startswith("mode: set\n")


def test_coverage_mode_atomic(rule_runner: RuleRunner) -> None:
    """`--go-test-cover-mode=atomic` must work for a package that does not import `sync/atomic`.

    `go tool cover -mode=atomic` rewrites the sources to call `sync/atomic.AddUint32`, so the
    covered package needs `sync/atomic` in its `importcfg` even though its own sources never
    imported it.
    """
    rule_runner.set_options(
        [
            "--test-use-coverage",
            "--go-test-cover-mode=atomic",
        ],
        env_inherit={"PATH"},
    )
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod(name='mod')\ngo_package()",
            "foo/go.mod": "module foo",
            # NB: deliberately imports nothing, and `sync/atomic` least of all.
            "foo/add.go": textwrap.dedent(
                """\
                package foo
                func add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """\
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
    result = _run_test(rule_runner, rule_runner.get_target(Address("foo")))
    assert result.exit_code == 0
    assert isinstance(result.coverage_data, GoCoverageData)

    profile = _coverage_profile(rule_runner, result.coverage_data)
    assert profile.startswith("mode: atomic\n")
    assert _covered_files(profile) == ["foo/add.go"]


def test_coverage_with_race_detector(rule_runner: RuleRunner) -> None:
    """Coverage must not make the race detector fire on the coverage counters.

    `set` and `count` instrumentation updates its counters without synchronization, so `go test`
    forces `atomic` whenever `-race` is enabled. Pants must do the same, or every covered package
    in a repo which enables the race detector reports races against itself.
    """
    rule_runner.write_files(
        {
            # NB: `race=True`, while `[go-test].cover_mode` is left at its `set` default.
            "foo/BUILD": "go_mod(name='mod', race=True)\ngo_package()",
            "foo/go.mod": "module foo",
            "foo/add.go": textwrap.dedent(
                """\
                package foo
                func add(x, y int) int {
                  return x + y
                }
                """
            ),
            "foo/add_test.go": textwrap.dedent(
                """\
                package foo
                import (
                  "sync"
                  "testing"
                )
                func TestAddConcurrently(t *testing.T) {
                  var wg sync.WaitGroup
                  for i := 0; i < 8; i++ {
                    wg.Add(1)
                    go func() {
                      defer wg.Done()
                      for j := 0; j < 200; j++ {
                        if add(2, 3) != 5 {
                          t.Error("bad sum")
                        }
                      }
                    }()
                  }
                  wg.Wait()
                }
                """
            ),
        }
    )
    result = _run_test(rule_runner, rule_runner.get_target(Address("foo")))
    assert b"DATA RACE" not in result.stdout_bytes
    assert b"DATA RACE" not in result.stderr_bytes
    assert result.exit_code == 0
    assert isinstance(result.coverage_data, GoCoverageData)

    # The race detector forces `atomic` even though `[go-test].cover_mode` is `set`.
    profile = _coverage_profile(rule_runner, result.coverage_data)
    assert profile.startswith("mode: atomic\n")
    assert _covered_files(profile) == ["foo/add.go"]
