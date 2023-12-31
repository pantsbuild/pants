# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable, Mapping

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.subsystems.scalatest import Scalatest
from pants.backend.scala.target_types import (
    ScalaSourcesGeneratorTarget,
    ScalatestTestsGeneratorTarget,
)
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.backend.scala.target_types import rules as target_types_rules
from pants.backend.scala.test.scalatest import ScalatestTestFieldSet, ScalatestTestRequest
from pants.backend.scala.test.scalatest import rules as scalatest_rules
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult, get_filtered_environment
from pants.core.target_types import FilesGeneratorTarget, FileTarget, RelocatedFiles
from pants.core.util_rules import config_files, source_files, stripped_source_files, system_binaries
from pants.engine.addresses import Addresses
from pants.engine.target import CoarsenedTargets
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as jdk_util_rules
from pants.jvm.non_jvm_dependencies import rules as non_jvm_dependencies_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner

# TODO(12812): Switch tests to using parsed scalatest.xml results instead of scanning stdout strings.


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *classpath.rules(),
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *jdk_util_rules(),
            *non_jvm_dependencies_rules(),
            *strip_jar.rules(),
            *scalac_rules(),
            *scalatest_rules(),
            *scala_target_types_rules(),
            *scalac_rules(),
            *source_files.rules(),
            *stripped_source_files.rules(),
            *system_binaries.rules(),
            *target_types_rules(),
            *util_rules(),
            get_filtered_environment,
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(TestResult, (ScalatestTestRequest.Batch,)),
            QueryRule(Scalatest, ()),
        ],
        target_types=[
            JvmArtifactTarget,
            FileTarget,
            FilesGeneratorTarget,
            RelocatedFiles,
            ScalaSourcesGeneratorTarget,
            ScalatestTestsGeneratorTarget,
        ],
    )
    return rule_runner


@pytest.fixture
def scalatest_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "scalatest.test.lock", ["org.scalatest:scalatest_2.13:3.2.10"]
    )


@pytest.fixture
def scalatest_lockfile(
    scalatest_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scalatest_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_simple_success(rule_runner: RuleRunner, scalatest_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": scalatest_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scalatest_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                scalatest_tests(
                    name='example-test',
                    dependencies= [
                        '3rdparty/jvm:org.scalatest_scalatest_2.13',
                    ],
                )
                """
            ),
            "SimpleSpec.scala": dedent(
                """
                package org.pantsbuild.example;

                import org.scalatest.funspec.AnyFunSpec

                class SimpleSpec extends AnyFunSpec {
                  describe("Simple") {
                    it("should be simple") {
                      assert("Simple".toLowerCase == "simple")
                    }
                  }
                }
                """
            ),
        }
    )

    test_result = run_scalatest_test(rule_runner, "example-test", "SimpleSpec.scala")

    assert test_result.exit_code == 0
    assert (
        b"Tests: succeeded 1, failed 0, canceled 0, ignored 0, pending 0"
        in test_result.stdout_bytes
    )
    assert test_result.xml_results and test_result.xml_results.files


@maybe_skip_jdk_test
def test_file_deps_success(rule_runner: RuleRunner, scalatest_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": scalatest_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scalatest_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                scala_sources(
                    name='example-sources',
                    dependencies=[':ducks'],
                )

                scalatest_tests(
                    name='example-test',
                    dependencies= [
                        '3rdparty/jvm:org.scalatest_scalatest_2.13',
                        ':example-sources',
                    ],
                )

                file(
                    name="ducks",
                    source="ducks.txt",
                )

                """
            ),
            "SimpleFileReader.scala": dedent(
                """
                package org.pantsbuild.example

                import java.nio.file.Files
                import java.nio.file.Path

                object SimpleFileReader {
                    def read(): String = Files.readString(Path.of("ducks.txt"))
                }
                """
            ),
            "SimpleSpec.scala": dedent(
                """
                package org.pantsbuild.example;

                import org.scalatest.funspec.AnyFunSpec
                import java.nio.file.Files
                import java.nio.file.Path

                class SimpleSpec extends AnyFunSpec {
                  describe("Ducks") {
                    it("should be ducks") {
                      val expectedFileContents = "lol ducks"

                      assert(SimpleFileReader.read() == expectedFileContents)
                      assert(Files.readString(Path.of("ducks.txt")) == expectedFileContents)
                    }
                  }
                }
                """
            ),
            "ducks.txt": "lol ducks",
        }
    )

    test_result = run_scalatest_test(rule_runner, "example-test", "SimpleSpec.scala")

    assert test_result.exit_code == 0
    assert (
        b"Tests: succeeded 1, failed 0, canceled 0, ignored 0, pending 0"
        in test_result.stdout_bytes
    )
    assert test_result.xml_results and test_result.xml_results.files


@maybe_skip_jdk_test
def test_extra_env_vars(rule_runner: RuleRunner, scalatest_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": scalatest_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scalatest_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
            scalatest_tests(
                name='example-test',
                dependencies= [
                    '3rdparty/jvm:org.scalatest_scalatest_2.13',
                ],
                extra_env_vars=[
                    "SCALATEST_TESTS_VAR_WITHOUT_VALUE",
                    "SCALATEST_TESTS_VAR_WITH_VALUE=scalatest_tests_var_with_value",
                    "SCALATEST_TESTS_OVERRIDE_WITH_VALUE_VAR=scalatest_tests_override_with_value_var_override",
                ],
            )
            """
            ),
            "ExtraEnvVarsSpec.scala": dedent(
                """
            package org.pantsbuild.example

            import org.scalatest.flatspec.AnyFlatSpec
            import org.scalatest.matchers.should.Matchers

            class ExtraEnvVarsSpec extends AnyFlatSpec with Matchers {
                "ExtraEnvVars" should "be readable from the test" in {
                    sys.env("ARG_WITH_VALUE_VAR") shouldBe "arg_with_value_var"
                    sys.env("ARG_WITHOUT_VALUE_VAR") shouldBe "arg_without_value_var"
                    sys.env("SCALATEST_TESTS_VAR_WITH_VALUE") shouldBe "scalatest_tests_var_with_value"
                    sys.env("SCALATEST_TESTS_VAR_WITHOUT_VALUE") shouldBe "scalatest_tests_var_without_value"
                    sys.env("SCALATEST_TESTS_OVERRIDE_WITH_VALUE_VAR") shouldBe "scalatest_tests_override_with_value_var_override"
                }
            }
            """
            ),
        }
    )

    test_result = run_scalatest_test(
        rule_runner,
        "example-test",
        "ExtraEnvVarsSpec.scala",
        extra_args=[
            '--test-extra-env-vars=["ARG_WITH_VALUE_VAR=arg_with_value_var", "ARG_WITHOUT_VALUE_VAR", "SCALATEST_TESTS_OVERRIDE_WITH_VALUE_VAR"]'
        ],
        env={
            "ARG_WITHOUT_VALUE_VAR": "arg_without_value_var",
            "SCALATEST_TESTS_VAR_WITHOUT_VALUE": "scalatest_tests_var_without_value",
            "SCALATEST_TESTS_OVERRIDE_WITH_VALUE_VAR": "scalatest_tests_override_with_value_var",
        },
    )
    assert test_result.exit_code == 0


def run_scalatest_test(
    rule_runner: RuleRunner,
    target_name: str,
    relative_file_path: str,
    *,
    extra_args: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> TestResult:
    args = extra_args or []
    rule_runner.set_options(args, env=env, env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(
        Address(spec_path="", target_name=target_name, relative_file_path=relative_file_path)
    )
    return rule_runner.request(
        TestResult, [ScalatestTestRequest.Batch("", (ScalatestTestFieldSet.create(tgt),), None)]
    )
