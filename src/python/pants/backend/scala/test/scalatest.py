# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass

from pants.backend.scala.subsystems.scalatest import Scalatest
from pants.backend.scala.target_types import ScalatestTestSourceField
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult, TestSubsystem
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, RemovePrefix, Snapshot
from pants.engine.process import BashBinary, FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import MaterializedClasspath, MaterializedClasspathRequest
from pants.jvm.resolve.jvm_tool import JvmToolLockfileRequest, JvmToolLockfileSentinel
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScalatestTestFieldSet(TestFieldSet):
    required_fields = (ScalatestTestSourceField,)

    sources: ScalatestTestSourceField


class ScalatestToolLockfileSentinel(JvmToolLockfileSentinel):
    options_scope = Scalatest.options_scope


@rule(desc="Run Scalatest", level=LogLevel.DEBUG)
async def run_scalatest_test(
    bash: BashBinary,
    jdk_setup: JdkSetup,
    scalatest: Scalatest,
    test_subsystem: TestSubsystem,
    field_set: ScalatestTestFieldSet,
) -> TestResult:
    classpath, scalatest_classpath = await MultiGet(
        Get(Classpath, Addresses([field_set.address])),
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
    reports_dir = f"{reports_dir_prefix}/{field_set.address.path_safe_spec}"

    # Classfiles produced by the root `scalatest_test` targets are the only ones which should run.
    user_classpath_arg = ":".join(classpath.root_args())

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                *jdk_setup.args(
                    bash,
                    [
                        *classpath.args(),
                        *scalatest_classpath.classpath_entries(toolcp_relpath),
                    ],
                ),
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
            description=f"Run Scalatest runner for {field_set.address}",
            level=LogLevel.DEBUG,
        ),
    )

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


# Required by standard test rules. Do nothing for now.
@rule(level=LogLevel.DEBUG)
async def setup_scalatest_debug_request(_field_set: ScalatestTestFieldSet) -> TestDebugRequest:
    raise NotImplementedError("TestDebugResult is not implemented for Scalatest (yet?).")


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
