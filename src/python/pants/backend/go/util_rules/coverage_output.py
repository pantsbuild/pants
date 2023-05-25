# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.subsystems.gotest import GoTestSubsystem
from pants.backend.go.util_rules import coverage_html
from pants.backend.go.util_rules.coverage import GoCoverageData
from pants.backend.go.util_rules.coverage_html import (
    RenderGoCoverageProfileToHtmlRequest,
    RenderGoCoverageProfileToHtmlResult,
)
from pants.core.goals.test import CoverageDataCollection, CoverageReports, FilesystemCoverageReport
from pants.core.util_rules import distdir
from pants.core.util_rules.distdir import DistDir
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, DigestContents, FileContent
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class GoCoverageDataCollection(CoverageDataCollection):
    element_type = GoCoverageData


@dataclass(frozen=True)
class RenderGoCoverageReportRequest(EngineAwareParameter):
    raw_report: GoCoverageData

    def debug_hint(self) -> str | None:
        return self.raw_report.import_path


@dataclass(frozen=True)
class RenderGoCoverageReportResult:
    coverage_report: FilesystemCoverageReport
    html_report: FilesystemCoverageReport | None = None


@rule
async def go_render_coverage_report(
    request: RenderGoCoverageReportRequest,
    distdir_value: DistDir,
    go_test_subsystem: GoTestSubsystem,
) -> RenderGoCoverageReportResult:
    output_dir = go_test_subsystem.coverage_output_dir(
        distdir=distdir_value,
        address=request.raw_report.pkg_target_address,
        import_path=request.raw_report.import_path,
    )
    snapshot, digest_contents = await MultiGet(
        Get(Snapshot, Digest, request.raw_report.coverage_digest),
        Get(DigestContents, Digest, request.raw_report.coverage_digest),
    )

    html_coverage_report: FilesystemCoverageReport | None = None
    if go_test_subsystem.coverage_html:
        html_result = await Get(
            RenderGoCoverageProfileToHtmlResult,
            RenderGoCoverageProfileToHtmlRequest(
                raw_coverage_profile=digest_contents[0].content,
                description_of_origin=f"Go package with import path `{request.raw_report.import_path}`",
                sources_digest=request.raw_report.sources_digest,
                sources_dir_path=request.raw_report.sources_dir_path,
            ),
        )
        html_report_snapshot = await Get(
            Snapshot,
            CreateDigest(
                [
                    FileContent(
                        path="coverage.html",
                        content=html_result.html_output,
                    )
                ]
            ),
        )

        html_coverage_report = FilesystemCoverageReport(
            coverage_insufficient=False,
            result_snapshot=html_report_snapshot,
            directory_to_materialize_to=output_dir,
            report_file=output_dir / "coverage.html",
            report_type="go_cover_html",
        )

    coverage_report = FilesystemCoverageReport(
        coverage_insufficient=False,
        result_snapshot=snapshot,
        directory_to_materialize_to=output_dir,
        report_file=output_dir / "cover.out",
        report_type="go_cover",
    )
    return RenderGoCoverageReportResult(
        coverage_report=coverage_report,
        html_report=html_coverage_report,
    )


@rule(desc="Merge Go coverage data", level=LogLevel.DEBUG)
async def go_gather_coverage_reports(
    raw_coverage_reports: GoCoverageDataCollection,
) -> CoverageReports:
    coverage_report_results = await MultiGet(
        Get(
            RenderGoCoverageReportResult,
            RenderGoCoverageReportRequest(
                raw_report=raw_coverage_report,
            ),
        )
        for raw_coverage_report in raw_coverage_reports
    )

    coverage_reports = []
    for result in coverage_report_results:
        coverage_reports.append(result.coverage_report)
        if result.html_report:
            coverage_reports.append(result.html_report)

    return CoverageReports(reports=tuple(coverage_reports))


def rules():
    return (
        *collect_rules(),
        *coverage_html.rules(),
        *distdir.rules(),
        UnionRule(CoverageDataCollection, GoCoverageDataCollection),
    )
