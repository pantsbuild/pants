# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.subsystems.scalatest import Scalatest
from pants.backend.scala.target_types import (
    ScalaSourcesGeneratorTarget,
    ScalatestTestsGeneratorTarget,
)
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.backend.scala.target_types import rules as target_types_rules
from pants.backend.scala.test.scalatest import ScalatestTestFieldSet
from pants.backend.scala.test.scalatest import rules as scalatest_rules
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.target import CoarsenedTargets
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as jdk_util_rules
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.coursier_test_util import TCoursierResolvedLockfile
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
            *external_tool_rules(),
            *jdk_util_rules(),
            *scalac_rules(),
            *scalatest_rules(),
            *scala_target_types_rules(),
            *scalac_rules(),
            *source_files.rules(),
            *target_types_rules(),
            *util_rules(),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(TestResult, (ScalatestTestFieldSet,)),
            QueryRule(Scalatest, ()),
        ],
        target_types=[
            JvmArtifactTarget,
            ScalaSourcesGeneratorTarget,
            ScalatestTestsGeneratorTarget,
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_simple_success(rule_runner: RuleRunner) -> None:
    scalatest = rule_runner.request(Scalatest, [])
    scalatest_coord = Coordinate(group="org.scalatest", artifact="scalatest_2.13", version="3.2.10")
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": TCoursierResolvedLockfile(
                scalatest.resolved_lockfile()
            ).serialize([ArtifactRequirement(coordinate=scalatest_coord)]),
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                  name = 'org.scalatest_scalatest',
                  group = '{scalatest_coord.group}',
                  artifact = '{scalatest_coord.artifact}',
                  version = '{scalatest_coord.version}',
                )

                scalatest_tests(
                    name='example-test',
                    dependencies= [
                        ':org.scalatest_scalatest',
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
    assert "Tests: succeeded 1, failed 0, canceled 0, ignored 0, pending 0" in test_result.stdout
    assert test_result.xml_results and test_result.xml_results.files


def run_scalatest_test(
    rule_runner: RuleRunner, target_name: str, relative_file_path: str
) -> TestResult:
    tgt = rule_runner.get_target(
        Address(spec_path="", target_name=target_name, relative_file_path=relative_file_path)
    )
    return rule_runner.request(TestResult, [ScalatestTestFieldSet.create(tgt)])
