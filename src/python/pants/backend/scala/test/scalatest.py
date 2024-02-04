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
from pants.core.goals.resolve_helpers import GenerateToolLockfileSentinel
from pants.core.goals.test import (
    TestDebugRequest,
    TestExtraEnv,
    TestFieldSet,
    TestRequest,
    TestResult,
    TestSubsystem,
)
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, RemovePrefix, Snapshot
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    Process,
    ProcessCacheScope,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesField, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
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


class ScalatestToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = Scalatest.options_scope


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
    jdk, transitive_tgts = await MultiGet(
        Get(JdkEnvironment, JdkRequest, JdkRequest.from_field(request.field_set.jdk_version)),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.field_set.address])),
    )

    lockfile_request = await Get(GenerateJvmLockfileFromTool, ScalatestToolLockfileSentinel())
    classpath, scalatest_classpath, files = await MultiGet(
        Get(Classpath, Addresses([request.field_set.address])),
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(
            SourceFiles,
            SourceFilesRequest(
                (dep.get(SourcesField) for dep in transitive_tgts.dependencies),
                for_sources_types=(FileSourceField,),
                enable_codegen=True,
            ),
        ),
    )

    input_digest = await Get(Digest, MergeDigests((*classpath.digests(), files.snapshot.digest)))

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

    field_set_extra_env = await Get(
        EnvironmentVars, EnvironmentVarsRequest(request.field_set.extra_env_vars.value or ())
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

    test_setup = await Get(TestSetup, TestSetupRequest(field_set, is_debug=False))
    process_result = await Get(FallibleProcessResult, JvmProcess, test_setup.process)
    reports_dir_prefix = test_setup.reports_dir_prefix

    xml_result_subset = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs([f"{reports_dir_prefix}/**"]))
    )
    xml_results = await Get(Snapshot, RemovePrefix(xml_result_subset, reports_dir_prefix))

    return TestResult.from_fallible_process_result(
        process_results=(process_result,),
        address=field_set.address,
        output_setting=test_subsystem.output,
        xml_results=xml_results,
    )


@rule(level=LogLevel.DEBUG)
async def setup_scalatest_debug_request(
    batch: ScalatestTestRequest.Batch[ScalatestTestFieldSet, Any]
) -> TestDebugRequest:
    setup = await Get(TestSetup, TestSetupRequest(batch.single_element, is_debug=True))
    process = await Get(Process, JvmProcess, setup.process)
    return TestDebugRequest(
        InteractiveProcess.from_process(process, forward_signals_to_process=False, restartable=True)
    )


@rule
def generate_scalatest_lockfile_request(
    _: ScalatestToolLockfileSentinel, scalatest: Scalatest
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(scalatest)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, ScalatestToolLockfileSentinel),
        *ScalatestTestRequest.rules(),
    ]
