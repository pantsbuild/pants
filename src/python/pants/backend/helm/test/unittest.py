# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from typing import Any

from pants.backend.helm.dependency_inference.unittest import rules as dependency_rules
from pants.backend.helm.subsystems.unittest import HelmUnitTestSubsystem
from pants.backend.helm.subsystems.unittest import rules as subsystem_rules
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartMetaSourceField,
    HelmChartTarget,
    HelmUnitTestDependenciesField,
    HelmUnitTestSourceField,
    HelmUnitTestStrictField,
    HelmUnitTestTestsGeneratorTarget,
    HelmUnitTestTestTarget,
    HelmUnitTestTimeoutField,
)
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.sources import HelmChartRoot, HelmChartRootRequest
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.goals.generate_snapshots import GenerateSnapshotsFieldSet, GenerateSnapshotsResult
from pants.core.goals.test import TestFieldSet, TestRequest, TestResult, TestSubsystem
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address
from pants.engine.fs import (
    AddPrefix,
    Digest,
    DigestSubset,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import FallibleProcessResult, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    SourcesField,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import Simplifier

logger = logging.getLogger(__name__)


class MissingUnitTestChartDependency(Exception):
    f"""Indicates that no chart has been found as dependency of the `{HelmUnitTestTestTarget.alias}` or
    `{HelmUnitTestTestsGeneratorTarget.alias}` targets."""

    def __init__(self, address: Address) -> None:
        super().__init__(
            f"No valid `{HelmChartTarget.alias}` target has been found as a dependency for target at '{address.spec}'."
        )


@dataclass(frozen=True)
class HelmUnitTestFieldSet(TestFieldSet, GenerateSnapshotsFieldSet):
    required_fields = (HelmUnitTestSourceField,)

    source: HelmUnitTestSourceField
    dependencies: HelmUnitTestDependenciesField
    strict: HelmUnitTestStrictField
    timeout: HelmUnitTestTimeoutField


class HelmUnitTestRequest(TestRequest):
    tool_subsystem = HelmUnitTestSubsystem
    field_set_type = HelmUnitTestFieldSet


@dataclass(frozen=True)
class HelmUnitTestSetup:
    chart: HelmChart
    chart_root: HelmChartRoot
    process: HelmProcess
    reports_output_directory: str
    snapshot_output_directories: tuple[str, ...]


@dataclass(frozen=True)
class HelmUnitTestSetupRequest:
    field_set: HelmUnitTestFieldSet
    description: str = dataclasses.field(compare=False)
    force: bool
    update_snapshots: bool
    timeout_seconds: int | None


@rule
async def setup_helm_unittest(
    request: HelmUnitTestSetupRequest, unittest_subsystem: HelmUnitTestSubsystem
) -> HelmUnitTestSetup:
    field_set = request.field_set
    direct_dep_targets, transitive_targets = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies)),
        Get(
            TransitiveTargets,
            TransitiveTargetsRequest([field_set.address]),
        ),
    )
    chart_targets = [tgt for tgt in direct_dep_targets if HelmChartFieldSet.is_applicable(tgt)]
    if len(chart_targets) == 0:
        raise MissingUnitTestChartDependency(field_set.address)

    chart_target = chart_targets[0]
    chart, chart_root, test_files, extra_files = await MultiGet(
        Get(HelmChart, HelmChartRequest, HelmChartRequest.from_target(chart_target)),
        Get(HelmChartRoot, HelmChartRootRequest(chart_target[HelmChartMetaSourceField])),
        Get(
            SourceFiles,
            SourceFilesRequest(sources_fields=[field_set.source]),
        ),
        Get(
            StrippedSourceFiles,
            SourceFilesRequest(
                sources_fields=[tgt.get(SourcesField) for tgt in transitive_targets.dependencies],
                for_sources_types=(ResourceSourceField, FileSourceField),
                enable_codegen=True,
            ),
        ),
    )

    stripped_test_files = await Get(
        Digest, RemovePrefix(test_files.snapshot.digest, chart_root.path)
    )
    merged_digests = await Get(
        Digest,
        MergeDigests(
            [
                chart.snapshot.digest,
                stripped_test_files,
                extra_files.snapshot.digest,
            ]
        ),
    )
    input_digest = await Get(Digest, AddPrefix(merged_digests, chart.name))

    reports_dir = "__reports_dir"
    reports_file = os.path.join(reports_dir, f"{field_set.address.path_safe_spec}.xml")

    snapshot_dirs = {
        os.path.join(
            chart.name, os.path.relpath(os.path.dirname(file), chart_root.path), "__snapshot__"
        )
        for file in test_files.snapshot.files
    }

    # Cache test runs only if they are successful, or not at all if `--test-force`.
    cache_scope = ProcessCacheScope.PER_SESSION if request.force else ProcessCacheScope.SUCCESSFUL

    process = HelmProcess(
        argv=[
            unittest_subsystem.plugin_name,
            # Always include colors and strip them out for display below (if required), for better cache
            # hit rates
            "--color",
            *(("--strict",) if field_set.strict.value else ()),
            *(("--update-snapshot",) if request.update_snapshots else ()),
            "--output-type",
            unittest_subsystem.output_type.value,
            "--output-file",
            reports_file,
            chart.name,
        ],
        description=request.description,
        input_digest=input_digest,
        cache_scope=cache_scope,
        timeout_seconds=request.timeout_seconds if request.timeout_seconds else None,
        output_directories=(reports_dir, *((snapshot_dirs) if request.update_snapshots else ())),
    )

    return HelmUnitTestSetup(
        chart,
        chart_root,
        process,
        reports_output_directory=reports_dir,
        snapshot_output_directories=tuple(snapshot_dirs),
    )


@rule(desc="Run Helm Unittest", level=LogLevel.DEBUG)
async def run_helm_unittest(
    batch: HelmUnitTestRequest.Batch[HelmUnitTestFieldSet, Any],
    test_subsystem: TestSubsystem,
    unittest_subsystem: HelmUnitTestSubsystem,
) -> TestResult:
    field_set = batch.single_element

    setup = await Get(
        HelmUnitTestSetup,
        HelmUnitTestSetupRequest(
            field_set,
            description=f"Running Helm unittest suite {field_set.address}",
            force=test_subsystem.force,
            update_snapshots=False,
            timeout_seconds=field_set.timeout.calculate_from_global_options(test_subsystem),
        ),
    )
    process_result = await Get(FallibleProcessResult, HelmProcess, setup.process)

    reports_digest = await Get(
        Digest,
        DigestSubset(
            process_result.output_digest,
            PathGlobs([os.path.join(setup.reports_output_directory, "**")]),
        ),
    )
    reports = await Get(Snapshot, RemovePrefix(reports_digest, setup.reports_output_directory))

    return TestResult.from_fallible_process_result(
        process_results=[process_result],
        address=field_set.address,
        output_setting=test_subsystem.output,
        xml_results=reports,
        output_simplifier=Simplifier(strip_formatting=not unittest_subsystem.color),
    )


@rule
async def generate_helm_unittest_snapshots(
    field_set: HelmUnitTestFieldSet,
) -> GenerateSnapshotsResult:
    setup = await Get(
        HelmUnitTestSetup,
        HelmUnitTestSetupRequest(
            field_set,
            description=f"Generating Helm unittest snapshots for suite {field_set.address}",
            force=False,
            update_snapshots=True,
            timeout_seconds=None,
        ),
    )

    process_result = await Get(ProcessResult, HelmProcess, setup.process)
    snapshot_output_digest = await Get(
        Digest,
        DigestSubset(
            process_result.output_digest,
            PathGlobs(
                [
                    os.path.join(snapshot_path, "*.snap")
                    for snapshot_path in setup.snapshot_output_directories
                ]
            ),
        ),
    )

    stripped_test_snapshot_output = await Get(
        Digest, RemovePrefix(snapshot_output_digest, setup.chart.name)
    )
    normalised_test_snapshots = await Get(
        Snapshot, AddPrefix(stripped_test_snapshot_output, setup.chart_root.path)
    )
    return GenerateSnapshotsResult(normalised_test_snapshots)


def rules():
    return [
        *collect_rules(),
        *subsystem_rules(),
        *dependency_rules(),
        *tool.rules(),
        *HelmUnitTestRequest.rules(),
        UnionRule(GenerateSnapshotsFieldSet, HelmUnitTestFieldSet),
    ]
