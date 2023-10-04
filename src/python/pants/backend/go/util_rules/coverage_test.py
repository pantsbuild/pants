# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

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
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.backend.go.util_rules.coverage import GoCoverageData
from pants.backend.go.util_rules.coverage_output import GoCoverageDataCollection
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
def rule_runner() -> RuleRunner:
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
        ],
        target_types=[GoModTarget, GoPackageTarget, FileTarget],
    )
    rule_runner.set_options(
        ["--go-test-args=-v -bench=.", "--test-use-coverage"], env_inherit={"PATH"}
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

    # Test that the `foo/adder` package is missing when it is **not** configured to be covered via
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
