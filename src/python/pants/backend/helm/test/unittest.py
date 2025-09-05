# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from typing import Any, cast

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
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest, get_helm_chart
from pants.backend.helm.util_rules.sources import (
    HelmChartRoot,
    HelmChartRootRequest,
    find_chart_source_root,
)
from pants.backend.helm.util_rules.tool import HelmProcess, helm_process
from pants.core.goals.generate_snapshots import GenerateSnapshotsFieldSet, GenerateSnapshotsResult
from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.core.goals.test import TestFieldSet, TestRequest, TestResult, TestSubsystem
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.engine.addresses import Address
from pants.engine.fs import AddPrefix, DigestSubset, MergeDigests, PathGlobs, RemovePrefix
from pants.engine.internals.graph import resolve_targets
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.intrinsics import (
    add_prefix,
    digest_subset_to_digest,
    digest_to_snapshot,
    merge_digests,
    remove_prefix,
)
from pants.engine.process import (
    ProcessCacheScope,
    ProcessWithRetries,
    execute_process_with_retry,
    fallible_to_exec_result_or_raise,
)
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import DependenciesRequest, SourcesField, TransitiveTargetsRequest
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
    tool_subsystem = cast(type[SkippableSubsystem], HelmUnitTestSubsystem)
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
    direct_dep_targets, transitive_targets = await concurrently(
        resolve_targets(**implicitly(DependenciesRequest(field_set.dependencies))),
        transitive_targets_get(TransitiveTargetsRequest([field_set.address]), **implicitly()),
    )
    chart_targets = [tgt for tgt in direct_dep_targets if HelmChartFieldSet.is_applicable(tgt)]
    if len(chart_targets) == 0:
        raise MissingUnitTestChartDependency(field_set.address)

    chart_target = chart_targets[0]
    chart, chart_root, test_files, extra_files = await concurrently(
        get_helm_chart(HelmChartRequest.from_target(chart_target), **implicitly()),
        find_chart_source_root(HelmChartRootRequest(chart_target[HelmChartMetaSourceField])),
        determine_source_files(SourceFilesRequest(sources_fields=[field_set.source])),
        strip_source_roots(
            **implicitly(
                SourceFilesRequest(
                    sources_fields=[
                        tgt.get(SourcesField) for tgt in transitive_targets.dependencies
                    ],
                    for_sources_types=(ResourceSourceField, FileSourceField),
                    enable_codegen=True,
                )
            )
        ),
    )

    stripped_test_files = await remove_prefix(
        RemovePrefix(test_files.snapshot.digest, chart_root.path)
    )
    merged_digests = await merge_digests(
        MergeDigests(
            [
                chart.snapshot.digest,
                stripped_test_files,
                extra_files.snapshot.digest,
            ]
        )
    )
    input_digest = await add_prefix(AddPrefix(merged_digests, chart.name))

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

    setup = await setup_helm_unittest(
        HelmUnitTestSetupRequest(
            field_set,
            description=f"Running Helm unittest suite {field_set.address}",
            force=test_subsystem.force,
            update_snapshots=False,
            timeout_seconds=field_set.timeout.calculate_from_global_options(test_subsystem),
        ),
        **implicitly(),
    )
    process = await helm_process(setup.process, **implicitly())
    process_results = await execute_process_with_retry(
        ProcessWithRetries(process, test_subsystem.attempts_default)
    )

    reports_digest = await digest_subset_to_digest(
        DigestSubset(
            process_results.last.output_digest,
            PathGlobs([os.path.join(setup.reports_output_directory, "**")]),
        )
    )
    reports = await digest_to_snapshot(
        **implicitly(RemovePrefix(reports_digest, setup.reports_output_directory))
    )

    return TestResult.from_fallible_process_result(
        process_results=process_results.results,
        address=field_set.address,
        output_setting=test_subsystem.output,
        xml_results=reports,
        output_simplifier=Simplifier(strip_formatting=not unittest_subsystem.color),
    )


@rule
async def generate_helm_unittest_snapshots(
    field_set: HelmUnitTestFieldSet,
) -> GenerateSnapshotsResult:
    setup = await setup_helm_unittest(
        HelmUnitTestSetupRequest(
            field_set,
            description=f"Generating Helm unittest snapshots for suite {field_set.address}",
            force=False,
            update_snapshots=True,
            timeout_seconds=None,
        ),
        **implicitly(),
    )

    process_result = await fallible_to_exec_result_or_raise(
        **implicitly({setup.process: HelmProcess})
    )
    snapshot_output_digest = await digest_subset_to_digest(
        DigestSubset(
            process_result.output_digest,
            PathGlobs(
                [
                    os.path.join(snapshot_path, "*.snap")
                    for snapshot_path in setup.snapshot_output_directories
                ]
            ),
        )
    )

    stripped_test_snapshot_output = await remove_prefix(
        RemovePrefix(snapshot_output_digest, setup.chart.name)
    )
    normalised_test_snapshots = await digest_to_snapshot(
        **implicitly(AddPrefix(stripped_test_snapshot_output, setup.chart_root.path))
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
