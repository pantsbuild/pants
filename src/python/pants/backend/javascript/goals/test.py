# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Any, Iterable

from pants.backend.javascript import install_node_package, nodejs_project_environment
from pants.backend.javascript.install_node_package import (
    InstalledNodePackage,
    InstalledNodePackageRequest,
)
from pants.backend.javascript.nodejs_project_environment import NodeJsProjectEnvironmentProcess
from pants.backend.javascript.package_json import NodePackageTestScriptField
from pants.backend.javascript.subsystems.nodejstest import NodeJSTest
from pants.backend.javascript.target_types import (
    JSSourceField,
    JSTestExtraEnvVarsField,
    JSTestSourceField,
    JSTestTimeoutField,
)
from pants.core.goals.test import TestExtraEnv, TestFieldSet, TestRequest, TestResult, TestSubsystem
from pants.core.target_types import AssetSourceField
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals import graph, platform_rules
from pants.engine.internals.native_engine import Digest, MergeDigests
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
    process = await Get(
        Process,
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=(
                "run",
                test_script.entry_point,
                "--",
                *sorted(map(relative_package_dir, field_set_source_files.files)),
            ),
            description=f"Running npm test for {field_set.address.spec}.",
            input_digest=merged_digest,
            level=LogLevel.INFO,
            extra_env=FrozenDict(**test_extra_env.env, **target_env_vars),
            timeout_seconds=field_set.timeout.calculate_from_global_options(test),
        ),
    )
    if test.force:
        process = dataclasses.replace(process, cache_scope=ProcessCacheScope.PER_SESSION)
    result = await Get(FallibleProcessResult, Process, process)
    return TestResult.from_fallible_process_result(result, field_set.address, test.output)


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *platform_rules.rules(),
        *graph.rules(),
        *nodejs_project_environment.rules(),
        *install_node_package.rules(),
        *source_files.rules(),
        *JSTestRequest.rules(),
        *collect_rules(),
    ]
