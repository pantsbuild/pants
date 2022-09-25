# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.test import GoTestFieldSet
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
            QueryRule(TestResult, (GoTestFieldSet,)),
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
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "PASS: TestAdd" in result.stdout
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
