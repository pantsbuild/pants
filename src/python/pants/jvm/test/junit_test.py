# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JunitTestsGeneratorTarget
from pants.backend.java.target_types import rules as target_types_rules
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.target_types import ScalaJunitTestsGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Addresses
from pants.engine.fs import FileDigest
from pants.engine.target import CoarsenedTargets
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as java_util_rules
from pants.jvm.resolve import user_resolves
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
)
from pants.jvm.resolve.coursier_test_util import TestCoursierWrapper
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.test.junit import JunitTestFieldSet
from pants.jvm.test.junit import rules as junit_rules
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner

# TODO(12812): Switch tests to using parsed junit.xml results instead of scanning stdout strings.


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *classpath.rules(),
            *config_files.rules(),
            *user_resolves.rules(),
            *java_util_rules(),
            *javac_rules(),
            *junit_rules(),
            *scala_target_types_rules(),
            *scalac_rules(),
            *source_files.rules(),
            *target_types_rules(),
            *util_rules(),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(TestResult, (JunitTestFieldSet,)),
        ],
        target_types=[
            JvmArtifactTarget,
            JavaSourcesGeneratorTarget,
            JunitTestsGeneratorTarget,
            ScalaJunitTestsGeneratorTarget,
        ],
    )
    rule_runner.set_options(
        # Makes JUnit output predictable and parseable across versions (#12933):
        args=["--junit-args=['--disable-ansi-colors','--details=flat','--details-theme=ascii']"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


JUNIT_COORD = Coordinate(group="junit", artifact="junit", version="4.13.2")
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
hamcrest_coord = Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3")
JUNIT4_RESOLVED_LOCKFILE = TestCoursierWrapper.new(
    entries=(
        CoursierLockfileEntry(
            coord=JUNIT_COORD,
            file_name="junit-4.13.2.jar",
            direct_dependencies=Coordinates([hamcrest_coord]),
            dependencies=Coordinates([hamcrest_coord]),
            file_digest=FileDigest(
                fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
                serialized_bytes_length=384581,
            ),
        ),
        CoursierLockfileEntry(
            coord=hamcrest_coord,
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
            "3rdparty/jvm/default.lock": JUNIT4_RESOLVED_LOCKFILE.serialize(
                [ArtifactRequirement(coordinate=JUNIT_COORD)]
            ),
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                  name = 'junit_junit',
                  group = '{JUNIT_COORD.group}',
                  artifact = '{JUNIT_COORD.artifact}',
                  version = '{JUNIT_COORD.version}',
                )
                junit_tests(
                    name='example-test',
                    dependencies= [
                        ':junit_junit',
                    ],

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
            "3rdparty/jvm/default.lock": JUNIT4_RESOLVED_LOCKFILE.serialize(
                [ArtifactRequirement(coordinate=JUNIT_COORD)]
            ),
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                  name = 'junit_junit',
                  group = '{JUNIT_COORD.group}',
                  artifact = '{JUNIT_COORD.artifact}',
                  version = '{JUNIT_COORD.version}',
                )
                junit_tests(
                    name='example-test',

                    dependencies= [
                        ':junit_junit',
                    ],
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
            "3rdparty/jvm/default.lock": JUNIT4_RESOLVED_LOCKFILE.serialize(
                [ArtifactRequirement(coordinate=JUNIT_COORD)]
            ),
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                  name = 'junit_junit',
                  group = '{JUNIT_COORD.group}',
                  artifact = '{JUNIT_COORD.artifact}',
                  version = '{JUNIT_COORD.version}',
                )

                java_sources(
                    name='example-lib',
                )

                junit_tests(
                    name = 'example-test',

                    dependencies = [
                        ':junit_junit',
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


@maybe_skip_jdk_test
def test_vintage_scala_simple_success(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": JUNIT4_RESOLVED_LOCKFILE.serialize(
                [ArtifactRequirement(coordinate=JUNIT_COORD)]
            ),
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                  name = 'junit_junit',
                  group = '{JUNIT_COORD.group}',
                  artifact = '{JUNIT_COORD.artifact}',
                  version = '{JUNIT_COORD.version}',
                )

                scala_junit_tests(
                    name='example-test',
                    dependencies= [
                        ':junit_junit',
                    ],
                )
                """
            ),
            "SimpleTest.scala": dedent(
                """
                package org.pantsbuild.example

                import junit.framework.TestCase
                import junit.framework.Assert._

                class SimpleTest extends TestCase {
                   def testHello(): Unit = {
                      assertTrue("Hello!" == "Hello!")
                   }
                }
                """
            ),
        }
    )

    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.scala")

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
JUPITER_COORD = Coordinate(group="org.junit.jupiter", artifact="junit-jupiter-api", version="5.7.2")
JUNIT5_RESOLVED_LOCKFILE = TestCoursierWrapper.new(
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
            coord=JUPITER_COORD,
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
            "3rdparty/jvm/default.lock": JUNIT5_RESOLVED_LOCKFILE.serialize(
                [ArtifactRequirement(coordinate=JUPITER_COORD)]
            ),
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                  name = 'org.junit.jupiter_junit-jupiter-api',
                  group = '{JUPITER_COORD.group}',
                  artifact = '{JUPITER_COORD.artifact}',
                  version = '{JUPITER_COORD.version}',
                )

                junit_tests(
                    name = 'example-test',

                    dependencies = [
                        ':org.junit.jupiter_junit-jupiter-api',
                    ],
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
    assert test_result.xml_results and test_result.xml_results.files
    assert re.search(r"Finished:\s+testHello", test_result.stdout) is not None
    assert re.search(r"1 tests successful", test_result.stdout) is not None
    assert re.search(r"1 tests found", test_result.stdout) is not None


@maybe_skip_jdk_test
def test_jupiter_simple_failure(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": JUNIT5_RESOLVED_LOCKFILE.serialize(
                [ArtifactRequirement(coordinate=JUPITER_COORD)]
            ),
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                  name = 'org.junit.jupiter_junit-jupiter-api',
                  group = '{JUPITER_COORD.group}',
                  artifact = '{JUPITER_COORD.artifact}',
                  version = '{JUPITER_COORD.version}',
                )
                junit_tests(
                    name='example-test',

                    dependencies= [
                        ':org.junit.jupiter_junit-jupiter-api',
                    ],
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
    assert test_result.xml_results and test_result.xml_results.files
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
            "3rdparty/jvm/default.lock": JUNIT5_RESOLVED_LOCKFILE.serialize(
                [ArtifactRequirement(coordinate=JUPITER_COORD)]
            ),
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                  name = 'org.junit.jupiter_junit-jupiter-api',
                  group = '{JUPITER_COORD.group}',
                  artifact = '{JUPITER_COORD.artifact}',
                  version = '{JUPITER_COORD.version}',
                )

                java_sources(
                    name='example-lib',

                )

                junit_tests(
                    name = 'example-test',

                    dependencies = [
                        ':org.junit.jupiter_junit-jupiter-api',
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


def run_junit_test(
    rule_runner: RuleRunner, target_name: str, relative_file_path: str
) -> TestResult:
    tgt = rule_runner.get_target(
        Address(spec_path="", target_name=target_name, relative_file_path=relative_file_path)
    )
    return rule_runner.request(TestResult, [JunitTestFieldSet.create(tgt)])
