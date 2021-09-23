# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.compile.javac_binary import rules as javac_binary_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JunitTestsGeneratorTarget
from pants.backend.java.target_types import rules as target_types_rules
from pants.backend.java.test.junit import JavaTestFieldSet
from pants.backend.java.test.junit import rules as junit_rules
from pants.backend.java.util_rules import rules as java_util_rules
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.fs import FileDigest
from pants.engine.target import CoarsenedTargets
from pants.jvm.resolve.coursier_fetch import (
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmArtifact, JvmDependencyLockfile
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner

# TODO(12812): Switch tests to using parsed junit.xml results instead of scanning stdout strings.


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *javac_rules(),
            *junit_rules(),
            *javac_binary_rules(),
            *util_rules(),
            *java_util_rules(),
            *target_types_rules(),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(TestResult, (JavaTestFieldSet,)),
        ],
        target_types=[
            JvmDependencyLockfile,
            JvmArtifact,
            JavaSourcesGeneratorTarget,
            JunitTestsGeneratorTarget,
        ],
        bootstrap_args=[
            "--javac-jdk=system",  # TODO(#12293): use a fixed JDK version.
            # Makes JUnit output predictable and parseable across versions (#12933):
            "--junit-args=['--disable-ansi-colors','--details=flat','--details-theme=ascii']",
        ],
    )


# This is hard-coded to make the test somewhat more hermetic.
# To regenerate (e.g. to update the resolved version), run the
# following in a test:
# resolved_lockfile = rule_runner.request(
#     CoursierResolvedLockfile,
#     [
#         MavenRequirements.create_from_maven_coordinates_fields(
#             fields=(),
#             additional_requirements=["junit:junit:4.13.2"],
#         )
#     ],
# )
# The `repr` of the resulting lockfile object can be directly copied
# into code to get the following:
JUNIT4_RESOLVED_LOCKFILE = CoursierResolvedLockfile(
    entries=(
        CoursierLockfileEntry(
            coord=Coordinate(group="junit", artifact="junit", version="4.13.2"),
            file_name="junit-4.13.2.jar",
            direct_dependencies=Coordinates(
                [Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3")]
            ),
            dependencies=Coordinates(
                [Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3")]
            ),
            file_digest=FileDigest(
                fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
                serialized_bytes_length=384581,
            ),
        ),
        CoursierLockfileEntry(
            coord=Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3"),
            file_name="hamcrest-core-1.3.jar",
            direct_dependencies=Coordinates([]),
            dependencies=Coordinates([]),
            file_digest=FileDigest(
                fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                serialized_bytes_length=45024,
            ),
        ),
    )
)


@maybe_skip_jdk_test
def test_vintage_simple_success(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": JUNIT4_RESOLVED_LOCKFILE.to_json().decode("utf-8"),
            "BUILD": dedent(
                """\
                jvm_artifact(
                  name = 'junit_junit',
                  group = 'junit',
                  artifact = 'junit',
                  version = '4.13.2',
                )
                coursier_lockfile(
                    name = 'lockfile',
                    requirements = [':junit_junit'],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                junit_tests(
                    name='example-test',
                    dependencies= [':lockfile'],
                )
                """
            ),
            "SimpleTest.java": dedent(
                """
                package org.pantsbuild.example;

                import junit.framework.TestCase;

                public class SimpleTest extends TestCase {
                   public void testHello(){
                      assertTrue("Hello!" == "Hello!");
                   }
                }
                """
            ),
        }
    )

    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.java")

    assert test_result.exit_code == 0
    assert re.search(r"Finished:\s+testHello", test_result.stdout) is not None
    assert re.search(r"1 tests successful", test_result.stdout) is not None
    assert re.search(r"1 tests found", test_result.stdout) is not None


@maybe_skip_jdk_test
def test_vintage_simple_failure(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": JUNIT4_RESOLVED_LOCKFILE.to_json().decode("utf-8"),
            "BUILD": dedent(
                """\
                jvm_artifact(
                  name = 'junit_junit',
                  group = 'junit',
                  artifact = 'junit',
                  version = '4.13.2',
                )
                coursier_lockfile(
                    name = 'lockfile',
                    requirements = [':junit_junit'],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                junit_tests(
                    name='example-test',
                    dependencies= [':lockfile'],
                )
                """
            ),
            "SimpleTest.java": dedent(
                """
                package org.pantsbuild.example;

                import org.junit.Test;
                import static org.junit.Assert.*;

                public class SimpleTest {
                   @Test
                   public void helloTest(){
                      assertTrue("Goodbye!" == "Hello!");
                   }
                }
                """
            ),
        }
    )

    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.java")

    assert test_result.exit_code == 1
    assert (
        re.search(
            r"Finished:.*?helloTest.*?Exception: java.lang.AssertionError",
            test_result.stdout,
            re.DOTALL,
        )
        is not None
    )
    assert re.search(r"1 tests failed", test_result.stdout) is not None
    assert re.search(r"1 tests found", test_result.stdout) is not None


@maybe_skip_jdk_test
def test_vintage_success_with_dep(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": JUNIT4_RESOLVED_LOCKFILE.to_json().decode("utf-8"),
            "BUILD": dedent(
                """\
                jvm_artifact(
                  name = 'junit_junit',
                  group = 'junit',
                  artifact = 'junit',
                  version = '4.13.2',
                )
                coursier_lockfile(
                    name = 'lockfile',
                    requirements = [':junit_junit'],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_sources(
                    name='example-lib',
                    dependencies = [
                        ':lockfile',                    ],
                )

                junit_tests(
                    name = 'example-test',
                    dependencies = [
                        ':lockfile',
                        '//:example-lib',
                    ],
                )
                """
            ),
            "ExampleLib.java": dedent(
                """
                package org.pantsbuild.example.lib;

                public class ExampleLib {
                    public static String hello() {
                        return "Hello!";
                    }
                }
                """
            ),
            "ExampleTest.java": dedent(
                """
                package org.pantsbuild.example;

                import org.pantsbuild.example.lib.ExampleLib;
                import junit.framework.TestCase;

                public class ExampleTest extends TestCase {
                   public void testHello(){
                      assertTrue(ExampleLib.hello() == "Hello!");
                   }
                }
                """
            ),
        }
    )

    test_result = run_junit_test(rule_runner, "example-test", "ExampleTest.java")

    assert test_result.exit_code == 0
    assert re.search(r"Finished:\s+testHello", test_result.stdout) is not None
    assert re.search(r"1 tests successful", test_result.stdout) is not None
    assert re.search(r"1 tests found", test_result.stdout) is not None


# This is hard-coded to make the test somewhat more hermetic.
# To regenerate (e.g. to update the resolved version), run the
# following in a test:
# resolved_lockfile = rule_runner.request(
#     CoursierResolvedLockfile,
#     [
#         MavenRequirements.create_from_maven_coordinates_fields(
#             fields=(),
#             additional_requirements=["org.junit.jupiter:junit-jupiter-api:5.7.2"],
#         )
#     ],
# )
# The `repr` of the resulting lockfile object can be directly copied
# into code to get the following:
JUNIT5_RESOLVED_LOCKFILE = CoursierResolvedLockfile(
    entries=(
        CoursierLockfileEntry(
            coord=Coordinate(group="org.apiguardian", artifact="apiguardian-api", version="1.1.0"),
            file_name="apiguardian-api-1.1.0.jar",
            direct_dependencies=Coordinates([]),
            dependencies=Coordinates([]),
            file_digest=FileDigest(
                fingerprint="a9aae9ff8ae3e17a2a18f79175e82b16267c246fbbd3ca9dfbbb290b08dcfdd4",
                serialized_bytes_length=2387,
            ),
        ),
        CoursierLockfileEntry(
            coord=Coordinate(
                group="org.junit.jupiter", artifact="junit-jupiter-api", version="5.7.2"
            ),
            file_name="junit-jupiter-api-5.7.2.jar",
            direct_dependencies=Coordinates(
                [
                    Coordinate(
                        group="org.apiguardian", artifact="apiguardian-api", version="1.1.0"
                    ),
                    Coordinate(
                        group="org.junit.platform",
                        artifact="junit-platform-commons",
                        version="1.7.2",
                    ),
                    Coordinate(group="org.opentest4j", artifact="opentest4j", version="1.2.0"),
                ]
            ),
            dependencies=Coordinates(
                [
                    Coordinate(
                        group="org.apiguardian", artifact="apiguardian-api", version="1.1.0"
                    ),
                    Coordinate(
                        group="org.junit.platform",
                        artifact="junit-platform-commons",
                        version="1.7.2",
                    ),
                    Coordinate(group="org.opentest4j", artifact="opentest4j", version="1.2.0"),
                ]
            ),
            file_digest=FileDigest(
                fingerprint="bc98326ecbc501e1860a2bc9780aebe5777bd29cf00059f88c2a56f48fbc9ce6",
                serialized_bytes_length=175588,
            ),
        ),
        CoursierLockfileEntry(
            coord=Coordinate(
                group="org.junit.platform", artifact="junit-platform-commons", version="1.7.2"
            ),
            file_name="junit-platform-commons-1.7.2.jar",
            direct_dependencies=Coordinates(
                [Coordinate(group="org.apiguardian", artifact="apiguardian-api", version="1.1.0")]
            ),
            dependencies=Coordinates(
                [Coordinate(group="org.apiguardian", artifact="apiguardian-api", version="1.1.0")]
            ),
            file_digest=FileDigest(
                fingerprint="738d0df021a0611fff5d277634e890cc91858fa72227cf0bcf36232a7caf014c",
                serialized_bytes_length=100008,
            ),
        ),
        CoursierLockfileEntry(
            coord=Coordinate(group="org.opentest4j", artifact="opentest4j", version="1.2.0"),
            file_name="opentest4j-1.2.0.jar",
            direct_dependencies=Coordinates([]),
            dependencies=Coordinates([]),
            file_digest=FileDigest(
                fingerprint="58812de60898d976fb81ef3b62da05c6604c18fd4a249f5044282479fc286af2",
                serialized_bytes_length=7653,
            ),
        ),
    )
)


@maybe_skip_jdk_test
def test_jupiter_simple_success(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": JUNIT5_RESOLVED_LOCKFILE.to_json().decode("utf-8"),
            "BUILD": dedent(
                """\
                jvm_artifact(
                  name='org.junit.jupiter_junit-jupiter-api',
                  group='org.junit.jupiter',
                  artifact='junit-jupiter-api',
                  version='5.7.2',
                )
                coursier_lockfile(
                    name = 'lockfile',
                    requirements = [
                        ':org.junit.jupiter_junit-jupiter-api',
                    ],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                junit_tests(
                    name = 'example-test',
                    dependencies = [':lockfile'],
                )
                """
            ),
            "SimpleTest.java": dedent(
                """
                package org.pantsbuild.example;

                import static org.junit.jupiter.api.Assertions.assertEquals;
                import org.junit.jupiter.api.Test;

                class SimpleTests {
                    @Test
                    void testHello(){
                      assertEquals("Hello!", "Hello!");
                   }
                }
                """
            ),
        }
    )

    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.java")

    assert test_result.exit_code == 0
    assert re.search(r"Finished:\s+testHello", test_result.stdout) is not None
    assert re.search(r"1 tests successful", test_result.stdout) is not None
    assert re.search(r"1 tests found", test_result.stdout) is not None


@maybe_skip_jdk_test
def test_jupiter_simple_failure(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": JUNIT5_RESOLVED_LOCKFILE.to_json().decode("utf-8"),
            "BUILD": dedent(
                """\
                jvm_artifact(
                  name='org.junit.jupiter_junit-jupiter-api',
                  group='org.junit.jupiter',
                  artifact='junit-jupiter-api',
                  version='5.7.2',
                )
                coursier_lockfile(
                    name = 'lockfile',
                    requirements = [
                        ':org.junit.jupiter_junit-jupiter-api',
                    ],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                junit_tests(
                    name='example-test',
                    dependencies= [':lockfile'],
                )
                """
            ),
            "SimpleTest.java": dedent(
                """
                package org.pantsbuild.example;

                import static org.junit.jupiter.api.Assertions.assertEquals;
                import org.junit.jupiter.api.Test;

                class SimpleTest {
                    @Test
                    void testHello(){
                      assertEquals("Goodbye!", "Hello!");
                   }
                }
                """
            ),
        }
    )

    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.java")

    assert test_result.exit_code == 1
    assert (
        re.search(
            r"Finished:.*?testHello.*?Exception: org.opentest4j.AssertionFailedError: expected: <Goodbye!> but was: <Hello!>",
            test_result.stdout,
            re.DOTALL,
        )
        is not None
    )
    assert re.search(r"1 tests failed", test_result.stdout) is not None
    assert re.search(r"1 tests found", test_result.stdout) is not None


@maybe_skip_jdk_test
def test_jupiter_success_with_dep(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": JUNIT5_RESOLVED_LOCKFILE.to_json().decode("utf-8"),
            "BUILD": dedent(
                """\
                jvm_artifact(
                  name='org.junit.jupiter_junit-jupiter-api',
                  group='org.junit.jupiter',
                  artifact='junit-jupiter-api',
                  version='5.7.2',
                )
                coursier_lockfile(
                    name = 'lockfile',
                    requirements = [
                        ':org.junit.jupiter_junit-jupiter-api',
                    ],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_sources(
                    name='example-lib',
                    dependencies = [
                        ':lockfile',
                    ],
                )

                junit_tests(
                    name = 'example-test',
                    dependencies = [
                        ':lockfile',
                        '//:example-lib',
                    ],
                )
                """
            ),
            "ExampleLib.java": dedent(
                """
                package org.pantsbuild.example.lib;

                public class ExampleLib {
                    public static String hello() {
                        return "Hello!";
                    }
                }
                """
            ),
            "SimpleTest.java": dedent(
                """
                package org.pantsbuild.example;

                import static org.junit.jupiter.api.Assertions.assertEquals;
                import org.junit.jupiter.api.Test;
                import org.pantsbuild.example.lib.ExampleLib;

                class SimpleTest {
                    @Test
                    void testHello(){
                      assertEquals(ExampleLib.hello(), "Hello!");
                   }
                }
                """
            ),
        }
    )

    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.java")

    assert test_result.exit_code == 0
    assert re.search(r"Finished:\s+testHello", test_result.stdout) is not None
    assert re.search(r"1 tests successful", test_result.stdout) is not None
    assert re.search(r"1 tests found", test_result.stdout) is not None


@maybe_skip_jdk_test
def test_vintage_and_jupiter_simple_success(rule_runner: RuleRunner) -> None:
    combined_lockfile = CoursierResolvedLockfile(
        entries=(*JUNIT4_RESOLVED_LOCKFILE.entries, *JUNIT5_RESOLVED_LOCKFILE.entries)
    )
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": combined_lockfile.to_json().decode("utf-8"),
            "BUILD": dedent(
                """\
                jvm_artifact(
                  name='junit_junit',
                  group='junit',
                  artifact='junit',
                  version='4.13.2',
                )
                jvm_artifact(
                  name='org.junit.jupiter_junit-jupiter-api',
                  group='org.junit.jupiter',
                  artifact='junit-jupiter-api',
                  version='5.7.2',
                )
                coursier_lockfile(
                    name = 'lockfile',
                    requirements = [
                        ':junit_junit',
                        ':org.junit.jupiter_junit-jupiter-api',
                    ],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                junit_tests(
                    name='example-test',
                    dependencies= [':lockfile'],
                )
                """
            ),
            "JupiterTest.java": dedent(
                """
                package org.pantsbuild.example;

                import static org.junit.jupiter.api.Assertions.assertEquals;
                import org.junit.jupiter.api.Test;

                class JupiterTest {
                    @Test
                    void testHello(){
                      assertEquals("Hello!", "Hello!");
                   }
                }
                """
            ),
            "VintageTest.java": dedent(
                """
                package org.pantsbuild.example;

                import junit.framework.TestCase;

                public class VintageTest extends TestCase {
                   public void testGoodbye(){
                      assertTrue("Hello!" == "Hello!");
                   }
                }
                """
            ),
        }
    )

    test_result = run_junit_test(rule_runner, "example-test", "JupiterTest.java")

    assert test_result.exit_code == 0
    # TODO: Once support for parsing junit.xml is implemented, use that to determine status so we can remove the
    #  hack to use ASCII test output in the `run_junit_test` rule.
    assert re.search(r"Finished:\s+testHello", test_result.stdout) is not None
    assert re.search(r"Finished:\s+testGoodbye", test_result.stdout) is not None
    assert re.search(r"2 tests successful", test_result.stdout) is not None
    assert re.search(r"2 tests found", test_result.stdout) is not None


def run_junit_test(
    rule_runner: RuleRunner, target_name: str, relative_file_path: str
) -> TestResult:
    tgt = rule_runner.get_target(
        Address(spec_path="", target_name=target_name, relative_file_path=relative_file_path)
    )
    return rule_runner.request(TestResult, [JavaTestFieldSet.create(tgt)])
