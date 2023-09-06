# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent
from typing import Iterable

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JunitTestsGeneratorTarget
from pants.backend.java.target_types import rules as target_types_rules
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.target_types import ScalaJunitTestsGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.core.goals.test import TestResult, get_filtered_environment
from pants.core.target_types import FilesGeneratorTarget, FileTarget, RelocatedFiles
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.target import CoarsenedTargets
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as java_util_rules
from pants.jvm.non_jvm_dependencies import rules as non_jvm_dependencies_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.test.junit import JunitTestRequest
from pants.jvm.test.junit import rules as junit_rules
from pants.jvm.test.testutil import run_junit_test
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner

# TODO(12812): Switch tests to using parsed junit.xml results instead of scanning stdout strings.


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *classpath.rules(),
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *java_util_rules(),
            *strip_jar.rules(),
            *javac_rules(),
            *junit_rules(),
            *scala_target_types_rules(),
            *scalac_rules(),
            *source_files.rules(),
            *target_types_rules(),
            *util_rules(),
            *non_jvm_dependencies_rules(),
            get_filtered_environment,
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(TestResult, (JunitTestRequest.Batch,)),
        ],
        target_types=[
            FileTarget,
            FilesGeneratorTarget,
            RelocatedFiles,
            JvmArtifactTarget,
            JavaSourcesGeneratorTarget,
            JunitTestsGeneratorTarget,
            ScalaJunitTestsGeneratorTarget,
        ],
    )
    return rule_runner


@pytest.fixture
def junit4_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "junit4.test.lock",
        ["junit:junit:4.13.2"],
    )


@pytest.fixture
def junit4_lockfile(
    junit4_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return junit4_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_vintage_simple_success(
    rule_runner: RuleRunner, junit4_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit4_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit4_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                junit_tests(
                    name='example-test',
                    dependencies= [
                        '3rdparty/jvm:junit_junit',
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
    stdout_text = test_result.stdout_bytes.decode()
    assert re.search(r"Finished:\s+testHello", stdout_text) is not None
    assert re.search(r"1 tests successful", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@maybe_skip_jdk_test
def test_vintage_simple_failure(
    rule_runner: RuleRunner, junit4_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit4_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit4_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                junit_tests(
                    name='example-test',

                    dependencies= [
                        '3rdparty/jvm:junit_junit',
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
    stdout_text = test_result.stdout_bytes.decode()
    assert (
        re.search(
            r"Finished:.*?helloTest.*?Exception: java.lang.AssertionError",
            stdout_text,
            re.DOTALL,
        )
        is not None
    )
    assert re.search(r"1 tests failed", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@maybe_skip_jdk_test
def test_vintage_success_with_dep(
    rule_runner: RuleRunner, junit4_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit4_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit4_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                java_sources(
                    name='example-lib',
                )

                junit_tests(
                    name = 'example-test',

                    dependencies = [
                        '3rdparty/jvm:junit_junit',
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
    stdout_text = test_result.stdout_bytes.decode()
    assert re.search(r"Finished:\s+testHello", stdout_text) is not None
    assert re.search(r"1 tests successful", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@maybe_skip_jdk_test
def test_vintage_scala_simple_success(
    rule_runner: RuleRunner, junit4_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit4_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit4_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                scala_junit_tests(
                    name='example-test',
                    dependencies= [
                        '3rdparty/jvm:junit_junit',
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
    stdout_text = test_result.stdout_bytes.decode()
    assert re.search(r"Finished:\s+testHello", stdout_text) is not None
    assert re.search(r"1 tests successful", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@pytest.fixture
def junit5_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "junit5.test.lock",
        ["org.junit.jupiter:junit-jupiter-api:5.7.2"],
    )


@pytest.fixture
def junit5_lockfile(
    junit5_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return junit5_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_jupiter_simple_success(
    rule_runner: RuleRunner, junit5_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit5_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit5_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                junit_tests(
                    name = 'example-test',

                    dependencies = [
                        '3rdparty/jvm:org.junit.jupiter_junit-jupiter-api',
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
    stdout_text = test_result.stdout_bytes.decode()
    assert re.search(r"Finished:\s+testHello", stdout_text) is not None
    assert re.search(r"1 tests successful", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@maybe_skip_jdk_test
def test_jupiter_simple_failure(
    rule_runner: RuleRunner, junit5_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit5_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit5_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                junit_tests(
                    name='example-test',

                    dependencies= [
                        '3rdparty/jvm:org.junit.jupiter_junit-jupiter-api',
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
    stdout_text = test_result.stdout_bytes.decode()
    assert (
        re.search(
            r"Finished:.*?testHello.*?Exception: org.opentest4j.AssertionFailedError: expected: <Goodbye!> but was: <Hello!>",
            stdout_text,
            re.DOTALL,
        )
        is not None
    )
    assert re.search(r"1 tests failed", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@maybe_skip_jdk_test
def test_jupiter_success_with_dep(
    rule_runner: RuleRunner, junit5_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit5_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit5_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                java_sources(
                    name='example-lib',

                )

                junit_tests(
                    name = 'example-test',

                    dependencies = [
                        '3rdparty/jvm:org.junit.jupiter_junit-jupiter-api',
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
    stdout_text = test_result.stdout_bytes.decode()
    assert re.search(r"Finished:\s+testHello", stdout_text) is not None
    assert re.search(r"1 tests successful", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


def _write_file_dependencies(
    rule_runner: RuleRunner,
    junit_deps: Iterable[str],
    path_to_read: str,
    junit4_lockfile: JVMLockfileFixture,
):
    junit_deps_str = ", ".join(f"'{i}'" for i in junit_deps)

    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit4_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit4_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                f"""\
                junit_tests(
                    name='example-test',
                    dependencies= [
                        '3rdparty/jvm:junit_junit',
                        {junit_deps_str}
                    ],
                )
                file(
                    name="duck",
                    source="ducks.txt",
                )
                files(
                    name="ducks",
                    sources=["*.txt"],
                )
                relocated_files(
                    name="relocated_ducks",
                    files_targets=[":duck"],
                    src="",
                    dest="ducks",
                )
                """
            ),
            "SimpleTest.java": dedent(
                f"""
                package org.pantsbuild.example;

                import junit.framework.TestCase;
                import java.nio.file.Files;
                import java.nio.file.Path;

                public class SimpleTest extends TestCase {{
                   public void testHello() throws Exception {{
                        assertEquals("lol ducks", Files.readString(Path.of("{path_to_read}")));
                   }}
                }}
                """
            ),
            "ducks.txt": "lol ducks",
        }
    )


@maybe_skip_jdk_test
def test_vintage_file_dependency(
    rule_runner: RuleRunner, junit4_lockfile: JVMLockfileFixture
) -> None:
    _write_file_dependencies(rule_runner, [":duck"], "ducks.txt", junit4_lockfile)
    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.java")

    assert test_result.exit_code == 0
    stdout_text = test_result.stdout_bytes.decode()
    assert re.search(r"Finished:\s+testHello", stdout_text) is not None
    assert re.search(r"1 tests successful", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@maybe_skip_jdk_test
def test_vintage_files_dependencies(
    rule_runner: RuleRunner, junit4_lockfile: JVMLockfileFixture
) -> None:
    _write_file_dependencies(rule_runner, [":ducks"], "ducks.txt", junit4_lockfile)

    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.java")

    assert test_result.exit_code == 0
    stdout_text = test_result.stdout_bytes.decode()
    assert re.search(r"Finished:\s+testHello", stdout_text) is not None
    assert re.search(r"1 tests successful", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@pytest.mark.skip  # TODO(14537) `relocated_files` doesn't presently work, un-skip when fixing that.
@pytest.mark.no_error_if_skipped
@maybe_skip_jdk_test
def test_vintage_relocated_files_dependency(
    rule_runner: RuleRunner, junit4_lockfile: JVMLockfileFixture
) -> None:
    _write_file_dependencies(rule_runner, [":relocated_ducks"], "ducks/ducks.txt", junit4_lockfile)

    test_result = run_junit_test(rule_runner, "example-test", "SimpleTest.java")

    assert test_result.exit_code == 0
    stdout_text = test_result.stdout_bytes.decode()
    assert re.search(r"Finished:\s+testHello", stdout_text) is not None
    assert re.search(r"1 tests successful", stdout_text) is not None
    assert re.search(r"1 tests found", stdout_text) is not None


@maybe_skip_jdk_test
def test_vintage_extra_env_vars(
    rule_runner: RuleRunner, junit4_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": junit4_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": junit4_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
            junit_tests(
                name="example-test",
                extra_env_vars=[
                    "JUNIT_TESTS_VAR_WITHOUT_VALUE",
                    "JUNIT_TESTS_VAR_WITH_VALUE=junit_tests_var_with_value",
                    "JUNIT_TESTS_OVERRIDE_WITH_VALUE_VAR=junit_tests_override_with_value_var_override",
                ],
            )
            """
            ),
            "ExtraEnvVarsTest.java": dedent(
                """\
            package org.pantsbuild.example;

            import junit.framework.TestCase;

            public class ExtraEnvVarsTest extends TestCase {
                public void testArgs() throws Exception {
                    assertEquals(System.getenv("ARG_WITH_VALUE_VAR"), "arg_with_value_var");
                    assertEquals(System.getenv("ARG_WITHOUT_VALUE_VAR"), "arg_without_value_var");
                    assertEquals(System.getenv("JUNIT_TESTS_VAR_WITH_VALUE"), "junit_tests_var_with_value");
                    assertEquals(System.getenv("JUNIT_TESTS_VAR_WITHOUT_VALUE"), "junit_tests_var_without_value");
                    assertEquals(System.getenv("JUNIT_TESTS_OVERRIDE_WITH_VALUE_VAR"), "junit_tests_override_with_value_var_override");
                }
            }
            """
            ),
        }
    )

    result = run_junit_test(
        rule_runner,
        "example-test",
        "ExtraEnvVarsTest.java",
        extra_args=[
            '--test-extra-env-vars=["ARG_WITH_VALUE_VAR=arg_with_value_var", "ARG_WITHOUT_VALUE_VAR", "JUNIT_TESTS_OVERRIDE_WITH_VALUE_VAR"]'
        ],
        env={
            "ARG_WITHOUT_VALUE_VAR": "arg_without_value_var",
            "JUNIT_TESTS_VAR_WITHOUT_VALUE": "junit_tests_var_without_value",
            "JUNIT_TESTS_OVERRIDE_WITH_VALUE_VAR": "junit_tests_override_with_value_var",
        },
    )
    assert result.exit_code == 0
