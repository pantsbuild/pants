# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass

from pants.backend.java.compile.javac import CompiledClassfiles, CompileJavaSourceRequest
from pants.backend.java.subsystems.junit import JUnit
from pants.backend.java.target_types import JavaTestsSources
from pants.backend.java.util_rules import JdkSetup
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult, TestSubsystem
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    CoursierLockfileForTargetRequest,
    CoursierResolvedLockfile,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavaTestFieldSet(TestFieldSet):
    required_fields = (JavaTestsSources,)

    sources: JavaTestsSources


@rule(desc="Run JUnit", level=LogLevel.DEBUG)
async def run_junit_test(
    jdk_setup: JdkSetup,
    junit: JUnit,
    test_subsystem: TestSubsystem,
    field_set: JavaTestFieldSet,
) -> TestResult:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(t.address for t in transitive_targets.closure)
    )
    lockfile = await Get(
        CoursierResolvedLockfile,
        CoursierLockfileForTargetRequest(Targets(transitive_targets.closure)),
    )
    materialized_classpath = await Get(
        MaterializedClasspath,
        MaterializedClasspathRequest(
            prefix="__thirdpartycp",
            lockfiles=(lockfile,),
            artifact_requirements=(
                ArtifactRequirements(
                    [
                        Coordinate(
                            group="org.junit.platform",
                            artifact="junit-platform-console",
                            version="1.7.2",
                        ),
                        Coordinate(
                            group="org.junit.jupiter",
                            artifact="junit-jupiter-engine",
                            version="5.7.2",
                        ),
                        Coordinate(
                            group="org.junit.vintage",
                            artifact="junit-vintage-engine",
                            version="5.7.2",
                        ),
                    ]
                ),
            ),
        ),
    )
    transitive_user_classfiles = await MultiGet(
        Get(CompiledClassfiles, CompileJavaSourceRequest(component=t)) for t in coarsened_targets
    )
    merged_transitive_user_classfiles_digest = await Get(
        Digest, MergeDigests(classfiles.digest for classfiles in transitive_user_classfiles)
    )
    usercp_relpath = "__usercp"
    prefixed_transitive_user_classfiles_digest = await Get(
        Digest, AddPrefix(merged_transitive_user_classfiles_digest, usercp_relpath)
    )
    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                prefixed_transitive_user_classfiles_digest,
                materialized_classpath.digest,
            )
        ),
    )
    proc = Process(
        argv=[
            f"{jdk_setup.java_home}/bin/java",
            "-cp",
            materialized_classpath.classpath_arg(),
            "org.junit.platform.console.ConsoleLauncher",
            "--classpath",
            usercp_relpath,
            "--scan-class-path",
            usercp_relpath,
            *junit.options.args,
        ],
        input_digest=merged_digest,
        description=f"Run JUnit 5 ConsoleLauncher against {field_set.address}",
        level=LogLevel.DEBUG,
    )

    process_result = await Get(
        FallibleProcessResult,
        Process,
        proc,
    )

    return TestResult.from_fallible_process_result(
        process_result,
        address=field_set.address,
        output_setting=test_subsystem.output,
    )


# Required by standard test rules. Do nothing for now.
@rule(level=LogLevel.DEBUG)
async def setup_junit_debug_request(_field_set: JavaTestFieldSet) -> TestDebugRequest:
    raise NotImplementedError("TestDebugResult is not implemented for JUnit (yet?).")


def rules():
    return [
        *collect_rules(),
        UnionRule(TestFieldSet, JavaTestFieldSet),
    ]
