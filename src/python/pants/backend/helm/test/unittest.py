# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass

from pants.backend.helm.dependency_inference.unittest import rules as dependency_rules
from pants.backend.helm.subsystems.unittest import HelmUnitTestSubsystem
from pants.backend.helm.subsystems.unittest import rules as subsystem_rules
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartTarget,
    HelmUnitTestChartField,
    HelmUnitTestDependenciesField,
    HelmUnitTestSourceField,
    HelmUnitTestTestsGeneratorTarget,
    HelmUnitTestTestTarget,
)
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult, TestSubsystem
from pants.core.target_types import ResourceSourceField
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address
from pants.engine.fs import AddPrefix, Digest, MergeDigests, RemovePrefix, Snapshot
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    SourcesField,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
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
    required_fields = (HelmUnitTestSourceField, HelmUnitTestChartField)

    source: HelmUnitTestSourceField
    chart: HelmUnitTestChartField
    dependencies: HelmUnitTestDependenciesField


@rule(desc="Run Helm Unittest", level=LogLevel.DEBUG)
async def run_helm_unittest(
    field_set: HelmUnitTestFieldSet,
    test_subsystem: TestSubsystem,
    unittest_subsystem: HelmUnitTestSubsystem,
) -> TestResult:
    chart_targets, transitive_targets = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.chart, include_special_cased_deps=True)),
        Get(
            TransitiveTargets,
            TransitiveTargetsRequest([field_set.address], include_special_cased_deps=False),
        ),
    )
    if len(chart_targets) == 0:
        raise MissingUnitTestChartDependency(field_set.address)

    chart = await Get(HelmChart, HelmChartRequest, HelmChartRequest.from_target(chart_targets[0]))

    source_files = await Get(
        StrippedSourceFiles,
        SourceFilesRequest(
            sources_fields=[
                field_set.source,
                *(
                    tgt.get(SourcesField)
                    for tgt in transitive_targets.dependencies
                    if not HelmChartFieldSet.is_applicable(tgt)
                ),
            ],
            for_sources_types=(HelmUnitTestSourceField, ResourceSourceField),
            enable_codegen=True,
        ),
    )
    prefixed_test_files_digest = await Get(
        Digest, AddPrefix(source_files.snapshot.digest, chart.path)
    )

    reports_dir = "__reports_dir"
    reports_file = os.path.join(reports_dir, f"{field_set.address.path_safe_spec}.xml")

    input_digest = await Get(
        Digest, MergeDigests([chart.snapshot.digest, prefixed_test_files_digest])
    )

    # Cache test runs only if they are successful, or not at all if `--test-force`.
    cache_scope = (
        ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )

    process_result = await Get(
        FallibleProcessResult,
        HelmProcess(
            argv=[
                unittest_subsystem.plugin_name,
                "--helm3",
                "--output-type",
                unittest_subsystem.output_type.value,
                "--output-file",
                reports_file,
                chart.path,
            ],
            description=f"Running Helm unittest on: {field_set.address}",
            input_digest=input_digest,
            cache_scope=cache_scope,
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


@rule
async def generate_helm_unittest_debug_request(field_set: HelmUnitTestFieldSet) -> TestDebugRequest:
    raise NotImplementedError("This is a stub")


def rules():
    return [
        *collect_rules(),
        *subsystem_rules(),
        *dependency_rules(),
        UnionRule(TestFieldSet, HelmUnitTestFieldSet),
    ]
