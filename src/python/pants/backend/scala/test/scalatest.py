# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pants.backend.scala.subsystems.scalatest import Scalatest
from pants.backend.scala.target_types import (
    ScalatestTestExtraEnvVarsField,
    ScalatestTestSourceField,
    ScalatestTestTimeoutField,
)
from pants.core.goals.resolves import ExportableTool
from pants.core.goals.test import (
    TestDebugRequest,
    TestExtraEnv,
    TestFieldSet,
    TestRequest,
    TestResult,
    TestSubsystem,
)
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.addresses import Addresses
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.fs import DigestSubset, MergeDigests, PathGlobs, RemovePrefix
from pants.engine.internals.graph import transitive_targets
from pants.engine.internals.platform_rules import environment_vars_subset
from pants.engine.intrinsics import digest_subset_to_digest, digest_to_snapshot, merge_digests
from pants.engine.process import (
    InteractiveProcess,
    ProcessCacheScope,
    ProcessWithRetries,
    execute_process_with_retry,
)
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import SourcesField, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.jvm.classpath import classpath as classpath_get
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import JdkRequest, JvmProcess, jvm_process, prepare_jdk_environment
from pants.jvm.resolve.coursier_fetch import ToolClasspathRequest, materialize_classpath_for_tool
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmDependenciesField, JvmJdkField
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScalatestTestFieldSet(TestFieldSet):
    required_fields = (
        ScalatestTestSourceField,
        JvmJdkField,
    )

    sources: ScalatestTestSourceField
    timeout: ScalatestTestTimeoutField
    jdk_version: JvmJdkField
    dependencies: JvmDependenciesField
    extra_env_vars: ScalatestTestExtraEnvVarsField


class ScalatestTestRequest(TestRequest):
    tool_subsystem = Scalatest
    field_set_type = ScalatestTestFieldSet
    supports_debug = True


@dataclass(frozen=True)
class TestSetupRequest:
    field_set: ScalatestTestFieldSet
    is_debug: bool


@dataclass(frozen=True)
class TestSetup:
    process: JvmProcess
    reports_dir_prefix: str


@rule(level=LogLevel.DEBUG)
async def setup_scalatest_for_target(
    request: TestSetupRequest,
    jvm: JvmSubsystem,
    scalatest: Scalatest,
    test_subsystem: TestSubsystem,
    test_extra_env: TestExtraEnv,
) -> TestSetup:
    jdk, transitive_tgts = await concurrently(
        prepare_jdk_environment(**implicitly(JdkRequest.from_field(request.field_set.jdk_version))),
        transitive_targets(TransitiveTargetsRequest([request.field_set.address]), **implicitly()),
    )

    lockfile_request = GenerateJvmLockfileFromTool.create(scalatest)
    classpath, scalatest_classpath, files = await concurrently(
        classpath_get(**implicitly(Addresses([request.field_set.address]))),
        materialize_classpath_for_tool(ToolClasspathRequest(lockfile=lockfile_request)),
        determine_source_files(
            SourceFilesRequest(
                (dep.get(SourcesField) for dep in transitive_tgts.dependencies),
                for_sources_types=(FileSourceField,),
                enable_codegen=True,
            )
        ),
    )

    input_digest = await merge_digests(MergeDigests((*classpath.digests(), files.snapshot.digest)))

    toolcp_relpath = "__toolcp"
    extra_immutable_input_digests = {
        toolcp_relpath: scalatest_classpath.digest,
    }

    reports_dir_prefix = "__reports_dir"
    reports_dir = f"{reports_dir_prefix}/{request.field_set.address.path_safe_spec}"

    # Classfiles produced by the root `scalatest_test` targets are the only ones which should run.
    user_classpath_arg = ":".join(classpath.root_args())

    # Cache test runs only if they are successful, or not at all if `--test-force`.
    cache_scope = (
        ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )

    extra_jvm_args: list[str] = []
    if request.is_debug:
        extra_jvm_args.extend(jvm.debug_args)

    field_set_extra_env = await environment_vars_subset(
        EnvironmentVarsRequest(request.field_set.extra_env_vars.value or ()), **implicitly()
    )

    process = JvmProcess(
        jdk=jdk,
        classpath_entries=[
            *classpath.args(),
            *scalatest_classpath.classpath_entries(toolcp_relpath),
        ],
        argv=[
            *extra_jvm_args,
            "org.scalatest.tools.Runner",
            # TODO: We currently give the entire user classpath to the JVM for startup (which
            # mixes it with the user classpath), and then only specify the roots to run here.
            #   see https://github.com/pantsbuild/pants/issues/13871
            *(("-R", user_classpath_arg) if user_classpath_arg else ()),
            "-o",
            "-u",
            reports_dir,
            *scalatest.args,
        ],
        input_digest=input_digest,
        extra_env={**test_extra_env.env, **field_set_extra_env},
        extra_jvm_options=scalatest.jvm_options,
        extra_immutable_input_digests=extra_immutable_input_digests,
        output_directories=(reports_dir,),
        description=f"Run Scalatest runner for {request.field_set.address}",
        timeout_seconds=request.field_set.timeout.calculate_from_global_options(test_subsystem),
        level=LogLevel.DEBUG,
        cache_scope=cache_scope,
        use_nailgun=False,
    )
    return TestSetup(process=process, reports_dir_prefix=reports_dir_prefix)


@rule(desc="Run Scalatest", level=LogLevel.DEBUG)
async def run_scalatest_test(
    test_subsystem: TestSubsystem,
    batch: ScalatestTestRequest.Batch[ScalatestTestFieldSet, Any],
) -> TestResult:
    field_set = batch.single_element

    test_setup = await setup_scalatest_for_target(
        TestSetupRequest(field_set, is_debug=False), **implicitly()
    )
    process = await jvm_process(**implicitly(test_setup.process))
    process_results = await execute_process_with_retry(
        ProcessWithRetries(process, test_subsystem.attempts_default)
    )
    reports_dir_prefix = test_setup.reports_dir_prefix

    xml_result_subset = await digest_subset_to_digest(
        DigestSubset(process_results.last.output_digest, PathGlobs([f"{reports_dir_prefix}/**"]))
    )
    xml_results = await digest_to_snapshot(
        **implicitly(RemovePrefix(xml_result_subset, reports_dir_prefix))
    )

    return TestResult.from_fallible_process_result(
        process_results=process_results.results,
        address=field_set.address,
        output_setting=test_subsystem.output,
        xml_results=xml_results,
    )


@rule(level=LogLevel.DEBUG)
async def setup_scalatest_debug_request(
    batch: ScalatestTestRequest.Batch[ScalatestTestFieldSet, Any],
) -> TestDebugRequest:
    setup = await setup_scalatest_for_target(
        TestSetupRequest(batch.single_element, is_debug=True), **implicitly()
    )
    process = await jvm_process(**implicitly(setup.process))
    return TestDebugRequest(
        InteractiveProcess.from_process(process, forward_signals_to_process=False, restartable=True)
    )


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(ExportableTool, Scalatest),
        *ScalatestTestRequest.rules(),
    ]
