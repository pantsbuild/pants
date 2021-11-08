# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass

from pants.backend.java.subsystems.junit import JUnit
from pants.backend.java.target_types import JavaTestSourceField
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult, TestSubsystem
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, RemovePrefix, Snapshot
from pants.engine.process import BashBinary, FallibleProcessResult, Process
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavaTestFieldSet(TestFieldSet):
    required_fields = (JavaTestSourceField,)

    sources: JavaTestSourceField


@rule(desc="Run JUnit", level=LogLevel.DEBUG)
async def run_junit_test(
    bash: BashBinary,
    jdk_setup: JdkSetup,
    junit: JUnit,
    test_subsystem: TestSubsystem,
    field_set: JavaTestFieldSet,
) -> TestResult:
    classpath = await Get(Classpath, Addresses([field_set.address]))
    junit_classpath = await Get(
        MaterializedClasspath,
        MaterializedClasspathRequest(
            prefix="__thirdpartycp",
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
    merged_digest = await Get(
        Digest,
        MergeDigests((classpath.content.digest, jdk_setup.digest, junit_classpath.digest)),
    )

    reports_dir_prefix = "__reports_dir"
    reports_dir = f"{reports_dir_prefix}/{field_set.address.path_safe_spec}"

    user_classpath_arg = ":".join(classpath.user_classpath_entries())

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                *jdk_setup.args(
                    bash, [*classpath.classpath_entries(), *junit_classpath.classpath_entries()]
                ),
                "org.junit.platform.console.ConsoleLauncher",
                *(("--classpath", user_classpath_arg) if user_classpath_arg else ()),
                *(("--scan-class-path", user_classpath_arg) if user_classpath_arg else ()),
                "--reports-dir",
                reports_dir,
                *junit.options.args,
            ],
            input_digest=merged_digest,
            output_directories=(reports_dir,),
            append_only_caches=jdk_setup.append_only_caches,
            env=jdk_setup.env,
            description=f"Run JUnit 5 ConsoleLauncher against {field_set.address}",
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
async def setup_junit_debug_request(_field_set: JavaTestFieldSet) -> TestDebugRequest:
    raise NotImplementedError("TestDebugResult is not implemented for JUnit (yet?).")


def rules():
    return [
        *collect_rules(),
        UnionRule(TestFieldSet, JavaTestFieldSet),
    ]
