# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.scala.bench.scalameter import (
    ScalameterBenchmarkFieldSet,
    ScalameterBenchmarkRequest,
)
from pants.backend.scala.bench.scalameter import rules as scalameter_rules
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.subsystems.scalameter import Scalameter
from pants.backend.scala.target_types import (
    ScalameterBenchmarksGeneratorTarget,
    ScalaSourcesGeneratorTarget,
)
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.core.goals.bench import BenchmarkResult, get_filtered_environment
from pants.core.target_types import FilesGeneratorTarget, FileTarget, RelocatedFiles
from pants.core.util_rules import config_files, source_files, stripped_source_files, system_binaries
from pants.engine.addresses import Address, Addresses
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
            *scala_target_types_rules(),
            *scalac_rules(),
            *scalameter_rules(),
            *source_files.rules(),
            *stripped_source_files.rules(),
            *system_binaries.rules(),
            *util_rules(),
            get_filtered_environment,
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(BenchmarkResult, (ScalameterBenchmarkRequest.Batch,)),
            QueryRule(Scalameter, ()),
        ],
        target_types=[
            JvmArtifactTarget,
            FileTarget,
            FilesGeneratorTarget,
            RelocatedFiles,
            ScalaSourcesGeneratorTarget,
            ScalameterBenchmarksGeneratorTarget,
        ],
    )
    return rule_runner


@pytest.fixture
def scalameter_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "scalameter.test.lock", ["com.storm-enroute:scalameter_2.13:0.21"]
    )


@pytest.fixture
def scalameter_lockfile(
    scalameter_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scalameter_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_simple_benchmark(rule_runner: RuleRunner, scalameter_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": scalameter_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scalameter_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
              scalameter_benchmarks(
                name='example-benchmark',
                dependencies=[
                  '3rdparty/jvm:com.storm-enroute_scalameter_2.13'
                ]
              )
              """
            ),
            "SimpleBenchmark.scala": dedent(
                """\
                import org.scalameter.api._

                class SimpleBenchmark extends Bench.LocalTime {
                  val ranges = for {
                    size <- Gen.range("size")(3000, 15000, 30000)
                  } yield 0 until size

                  measure method "map" in {
                    using(ranges) curve("Range") in {
                      _.map(_ + 1)
                    }
                  }
                }
                """
            ),
        }
    )

    bench_result = run_scalameter_benchmark(
        rule_runner, "example-benchmark", "SimpleBenchmark.scala"
    )

    assert bench_result.exit_code == 0
    assert bench_result.reports


def run_scalameter_benchmark(
    rule_runner: RuleRunner, target_name: str, relative_file_path: str
) -> BenchmarkResult:
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(
        Address(
            spec_path="",
            target_name=target_name,
            relative_file_path=relative_file_path,
        )
    )
    return rule_runner.request(
        BenchmarkResult,
        [ScalameterBenchmarkRequest.Batch("", (ScalameterBenchmarkFieldSet.create(tgt),), None)],
    )
