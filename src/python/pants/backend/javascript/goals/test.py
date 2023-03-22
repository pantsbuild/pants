# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Iterable

from pants.backend.javascript import install_node_package, nodejs_project_environment
from pants.backend.javascript.install_node_package import (
    InstalledNodePackage,
    InstalledNodePackageRequest,
)
from pants.backend.javascript.nodejs_project_environment import NodeJsProjectEnvironmentProcess
from pants.backend.javascript.package_json import NodePackageTestScriptField, NodeTestScript
from pants.backend.javascript.subsystems.nodejstest import NodeJSTest
from pants.backend.javascript.target_types import (
    JSSourceField,
    JSTestExtraEnvVarsField,
    JSTestSourceField,
    JSTestTimeoutField,
)
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.build_graph.address import Address
from pants.core.goals.test import (
    CoverageData,
    CoverageDataCollection,
    CoverageReports,
    FilesystemCoverageReport,
    TestExtraEnv,
    TestFieldSet,
    TestRequest,
    TestResult,
    TestSubsystem,
)
from pants.core.target_types import AssetSourceField
from pants.core.util_rules import source_files
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import DigestSubset, GlobExpansionConjunction
from pants.engine.internals import graph, platform_rules
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    SourcesField,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class JSCoverageData(CoverageData):
    snapshot: Snapshot
    address: Address
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    working_directory: str


class JSCoverageDataCollection(CoverageDataCollection[JSCoverageData]):
    element_type = JSCoverageData


@dataclass(frozen=True)
class JSTestFieldSet(TestFieldSet):
    required_fields = (JSTestSourceField,)

    source: JSTestSourceField
    dependencies: Dependencies
    timeout: JSTestTimeoutField
    extra_env_vars: JSTestExtraEnvVarsField


class JSTestRequest(TestRequest):
    tool_subsystem = NodeJSTest
    field_set_type = JSTestFieldSet


@rule(level=LogLevel.DEBUG, desc="Run javascript tests")
async def run_javascript_tests(
    batch: JSTestRequest.Batch[JSTestFieldSet, Any],
    test: TestSubsystem,
    test_extra_env: TestExtraEnv,
) -> TestResult:
    field_set = batch.single_element
    installation_get = Get(InstalledNodePackage, InstalledNodePackageRequest(field_set.address))
    transitive_tgts_get = Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))

    field_set_source_files_get = Get(SourceFiles, SourceFilesRequest([field_set.source]))
    target_env_vars_get = Get(
        EnvironmentVars, EnvironmentVarsRequest(field_set.extra_env_vars.sorted())
    )
    installation, transitive_tgts, field_set_source_files, target_env_vars = await MultiGet(
        installation_get, transitive_tgts_get, field_set_source_files_get, target_env_vars_get
    )

    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            (tgt.get(SourcesField) for tgt in transitive_tgts.closure),
            enable_codegen=True,
            for_sources_types=[JSSourceField, AssetSourceField],
        ),
    )
    merged_digest = await Get(Digest, MergeDigests([sources.snapshot.digest, installation.digest]))

    def relative_package_dir(file: str) -> str:
        return os.path.relpath(file, installation.project_env.package_dir())

    test_script = installation.project_env.ensure_target()[NodePackageTestScriptField].value
    entry_point = test_script.entry_point

    coverage_args: tuple[str, ...] = ()
    output_files: list[str] = []
    output_directories: list[str] = []
    if test.use_coverage and test_script.supports_coverage():
        coverage_args = test_script.coverage_args
        output_files.extend(test_script.coverage_output_files)
        output_directories.extend(test_script.coverage_output_directories)
        entry_point = test_script.coverage_entry_point or entry_point

    process = await Get(
        Process,
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=(
                "run",
                entry_point,
                "--",
                *sorted(map(relative_package_dir, field_set_source_files.files)),
                *coverage_args,
            ),
            description=f"Running npm test for {field_set.address.spec}.",
            input_digest=merged_digest,
            level=LogLevel.INFO,
            extra_env=FrozenDict(**test_extra_env.env, **target_env_vars),
            timeout_seconds=field_set.timeout.calculate_from_global_options(test),
            output_files=tuple(output_files),
            output_directories=tuple(output_directories),
        ),
    )
    if test.force:
        process = dataclasses.replace(process, cache_scope=ProcessCacheScope.PER_SESSION)

    result = await Get(FallibleProcessResult, Process, process)
    coverage_data: JSCoverageData | None = None
    if test.use_coverage:
        coverage_snapshot = await Get(
            Snapshot,
            DigestSubset(
                result.output_digest,
                test_script.coverage_globs(installation.project_env.relative_workspace_directory()),
            ),
        )
        coverage_data = JSCoverageData(
            coverage_snapshot,
            field_set.address,
            output_files=test_script.coverage_output_files,
            output_directories=test_script.coverage_output_directories,
            working_directory=installation.project_env.relative_workspace_directory(),
        )

    return TestResult.from_fallible_process_result(
        result, field_set.address, test.output, coverage_data=coverage_data
    )


@rule(desc="Collecting coverage reports.")
async def collect_coverage_reports(
    coverage_reports: JSCoverageDataCollection,
    dist_dir: DistDir,
    nodejs_test: NodeJSTest,
) -> CoverageReports:
    gets_per_data = [
        (
            file,
            report,
            Get(
                Snapshot,
                DigestSubset(
                    report.snapshot.digest,
                    NodeTestScript.coverage_globs_for(
                        report.working_directory,
                        (file,),
                        report.output_directories,
                        GlobMatchErrorBehavior.error,
                        GlobExpansionConjunction.all_match,
                        description_of_origin="the JS coverage report collection rule",
                    ),
                ),
            ),
        )
        for report in coverage_reports
        for file in report.output_files
    ]
    snapshots = await MultiGet(get for file, report, get in gets_per_data)
    return CoverageReports(
        tuple(
            _get_report(nodejs_test, dist_dir, snapshot, data.address, file)
            for (file, data), snapshot in zip(
                ((file, report) for file, report, get in gets_per_data), snapshots
            )
        )
    )


def _get_report(
    nodejs_test: NodeJSTest,
    dist_dir: DistDir,
    snapshot: Snapshot,
    address: Address,
    file: str,
) -> FilesystemCoverageReport:
    # It is up to the user to configure the output coverage reports.
    file_path = PurePath(file)
    output_dir = nodejs_test.render_coverage_output_dir(dist_dir, address)
    return FilesystemCoverageReport(
        coverage_insufficient=False,
        result_snapshot=snapshot,
        directory_to_materialize_to=output_dir,
        report_file=output_dir / file_path,
        report_type=file_path.suffix,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *platform_rules.rules(),
        *graph.rules(),
        *nodejs_project_environment.rules(),
        *install_node_package.rules(),
        *source_files.rules(),
        *JSTestRequest.rules(),
        UnionRule(CoverageDataCollection, JSCoverageDataCollection),
        *collect_rules(),
    ]
