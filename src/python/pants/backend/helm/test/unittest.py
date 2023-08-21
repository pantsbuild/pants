# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
from pants.core.goals.test import TestFieldSet, TestRequest, TestResult, TestSubsystem
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address
from pants.engine.fs import AddPrefix, Digest, MergeDigests, RemovePrefix, Snapshot
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    SourcesField,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class MissingUnitTestChartDependency(Exception):
    f"""Indicates that no chart has been found as dependency of the `{HelmUnitTestTestTarget.alias}` or
    `{HelmUnitTestTestsGeneratorTarget.alias}` targets."""

    def __init__(self, address: Address) -> None:
        super().__init__(
            f"No valid `{HelmChartTarget.alias}` target has been found as a dependency for target at '{address.spec}'."
        )


@dataclass(frozen=True)
class HelmUnitTestFieldSet(TestFieldSet):
    required_fields = (HelmUnitTestSourceField,)

    source: HelmUnitTestSourceField
    dependencies: HelmUnitTestDependenciesField
    strict: HelmUnitTestStrictField
    timeout: HelmUnitTestTimeoutField


class HelmUnitTestRequest(TestRequest):
    tool_subsystem = HelmUnitTestSubsystem
    field_set_type = HelmUnitTestFieldSet


@rule(desc="Run Helm Unittest", level=LogLevel.DEBUG)
async def run_helm_unittest(
    batch: HelmUnitTestRequest.Batch[HelmUnitTestFieldSet, Any],
    test_subsystem: TestSubsystem,
    unittest_subsystem: HelmUnitTestSubsystem,
) -> TestResult:
    field_set = batch.single_element

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

    reports_dir = "__reports_dir"
    reports_file = os.path.join(reports_dir, f"{field_set.address.path_safe_spec}.xml")

    merged_digests = await Get(
        Digest,
        MergeDigests([chart.snapshot.digest, stripped_test_files, extra_files.snapshot.digest]),
    )
    input_digest = await Get(Digest, AddPrefix(merged_digests, chart.name))

    # Cache test runs only if they are successful, or not at all if `--test-force`.
    cache_scope = (
        ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )

    strict = field_set.strict.value
    process_result = await Get(
        FallibleProcessResult,
        HelmProcess(
            argv=[
                unittest_subsystem.plugin_name,
                "--helm3",
                *(("--color",) if unittest_subsystem.color else ()),
                *(("--strict",) if strict else ()),
                "--output-type",
                unittest_subsystem.output_type.value,
                "--output-file",
                reports_file,
                chart.name,
            ],
            description=f"Running Helm unittest suite {field_set.address}",
            input_digest=input_digest,
            cache_scope=cache_scope,
            timeout_seconds=field_set.timeout.calculate_from_global_options(test_subsystem),
            output_directories=(reports_dir,),
        ),
    )
    xml_results = await Get(Snapshot, RemovePrefix(process_result.output_digest, reports_dir))

    return TestResult.from_fallible_process_result(
        process_result,
        address=field_set.address,
        output_setting=test_subsystem.output,
        xml_results=xml_results,
    )


def rules():
    return [
        *collect_rules(),
        *subsystem_rules(),
        *dependency_rules(),
        *tool.rules(),
        *HelmUnitTestRequest.rules(),
    ]
