# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass

from pants.backend.scala.subsystems.scalatest import Scalatest
from pants.backend.scala.target_types import ScalatestTestSourceField
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult, TestSubsystem
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, RemovePrefix, Snapshot
from pants.engine.process import (
    BashBinary,
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessRequest,
    Process,
    ProcessCacheScope,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import MaterializedClasspath, MaterializedClasspathRequest
from pants.jvm.resolve.jvm_tool import JvmToolLockfileRequest, JvmToolLockfileSentinel
from pants.jvm.subsystems import JvmSubsystem
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScalatestTestFieldSet(TestFieldSet):
    required_fields = (ScalatestTestSourceField,)

    sources: ScalatestTestSourceField


class ScalatestToolLockfileSentinel(JvmToolLockfileSentinel):
    resolve_name = Scalatest.options_scope


@dataclass(frozen=True)
class TestSetupRequest:
    field_set: ScalatestTestFieldSet
    is_debug: bool


@dataclass(frozen=True)
class TestSetup:
    process: Process
    reports_dir_prefix: str


@rule(level=LogLevel.DEBUG)
async def setup_scalatest_for_target(
    request: TestSetupRequest,
    bash: BashBinary,
    jdk_setup: JdkSetup,
    jvm: JvmSubsystem,
    scalatest: Scalatest,
    test_subsystem: TestSubsystem,
) -> TestSetup:
    classpath, scalatest_classpath = await MultiGet(
        Get(Classpath, Addresses([request.field_set.address])),
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(lockfiles=(scalatest.resolved_lockfile(),)),
        ),
    )

    merged_classpath_digest = await Get(Digest, MergeDigests(classpath.digests()))

    toolcp_relpath = "__toolcp"
    immutable_input_digests = {
        **jdk_setup.immutable_input_digests,
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

    process = Process(
        argv=[
            *jdk_setup.args(
                bash,
                [
                    *classpath.args(),
                    *scalatest_classpath.classpath_entries(toolcp_relpath),
                ],
            ),
            *extra_jvm_args,
            "org.scalatest.tools.Runner",
            # TODO: We currently give the entire user classpath to the JVM for startup (which
            # mixes it with the user classpath), and then only specify the roots to run here.
            #   see https://github.com/pantsbuild/pants/issues/13871
            *(("-R", user_classpath_arg) if user_classpath_arg else ()),
            "-o",
            "-u",
            reports_dir,
            *scalatest.options.args,
        ],
        input_digest=merged_classpath_digest,
        immutable_input_digests=immutable_input_digests,
        output_directories=(reports_dir,),
        append_only_caches=jdk_setup.append_only_caches,
        env=jdk_setup.env,
        description=f"Run Scalatest runner for {request.field_set.address}",
        level=LogLevel.DEBUG,
        cache_scope=cache_scope,
    )
    return TestSetup(process=process, reports_dir_prefix=reports_dir_prefix)


@rule(desc="Run Scalatest", level=LogLevel.DEBUG)
async def run_scalatest_test(
    test_subsystem: TestSubsystem,
    field_set: ScalatestTestFieldSet,
) -> TestResult:
    test_setup = await Get(TestSetup, TestSetupRequest(field_set, is_debug=False))
    process_result = await Get(FallibleProcessResult, Process, test_setup.process)
    reports_dir_prefix = test_setup.reports_dir_prefix

    xml_result_subset = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs([f"{reports_dir_prefix}/**"]))
    )
    xml_results = await Get(Snapshot, RemovePrefix(xml_result_subset, reports_dir_prefix))

    return TestResult.from_fallible_process_result(
        process_result,
        address=field_set.address,
        output_setting=test_subsystem.output,
        xml_results=xml_results,
    )


@rule(level=LogLevel.DEBUG)
async def setup_scalatest_debug_request(field_set: ScalatestTestFieldSet) -> TestDebugRequest:
    setup = await Get(TestSetup, TestSetupRequest(field_set, is_debug=True))
    interactive_process = await Get(
        InteractiveProcess,
        InteractiveProcessRequest(
            setup.process, forward_signals_to_process=False, restartable=True
        ),
    )
    return TestDebugRequest(interactive_process)


@rule
async def generate_scalatest_lockfile_request(
    _: ScalatestToolLockfileSentinel, scalatest: Scalatest
) -> JvmToolLockfileRequest:
    return JvmToolLockfileRequest.from_tool(scalatest)


def rules():
    return [
        *collect_rules(),
        UnionRule(TestFieldSet, ScalatestTestFieldSet),
        UnionRule(JvmToolLockfileSentinel, ScalatestToolLockfileSentinel),
    ]
