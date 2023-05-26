# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, cast

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.subsystems.jmh import Jmh
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JmhBenckmarksGeneratorTarget
from pants.backend.java.target_types import rules as java_target_types_rules
from pants.backend.kotlin.compile import kotlinc, kotlinc_plugins
from pants.backend.kotlin.target_types import KotlinJmhBenckmarksGeneratorTarget
from pants.backend.kotlin.target_types import rules as kotlin_target_types_rules
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.target_types import ScalaJmhBenchmarksGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.core.goals.bench import BenchmarkResult, get_filtered_environment
from pants.core.target_types import FilesGeneratorTarget, FileTarget, RelocatedFiles
from pants.core.util_rules import config_files, source_files, stripped_source_files, system_binaries
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import DigestContents
from pants.engine.target import CoarsenedTargets
from pants.jvm import classpath
from pants.jvm.bench.jmh import JmhBenchmarkFieldSet, JmhBenchmarkRequest
from pants.jvm.bench.jmh import rules as jmh_rules
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
            *jmh_rules(),
            *javac_rules(),
            *java_target_types_rules(),
            *kotlinc.rules(),
            *kotlinc_plugins.rules(),
            *kotlin_target_types_rules(),
            *scalac_rules(),
            *scala_target_types_rules(),
            *source_files.rules(),
            *stripped_source_files.rules(),
            *system_binaries.rules(),
            *util_rules(),
            get_filtered_environment,
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(BenchmarkResult, (JmhBenchmarkRequest.Batch,)),
            QueryRule(Jmh, ()),
        ],
        target_types=[
            JvmArtifactTarget,
            FileTarget,
            FilesGeneratorTarget,
            RelocatedFiles,
            JavaSourcesGeneratorTarget,
            JmhBenckmarksGeneratorTarget,
            ScalaJmhBenchmarksGeneratorTarget,
            KotlinJmhBenckmarksGeneratorTarget,
        ],
    )
    return rule_runner


_JMH_VERSION = "1.36"


@pytest.fixture
def jmh_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "jmh.test.lock",
        [
            f"org.openjdk.jmh:jmh-core:{_JMH_VERSION}",
            f"org.openjdk.jmh:jmh-generator-bytecode:{_JMH_VERSION}",
            f"org.openjdk.jmh:jmh-generator-reflection:{_JMH_VERSION}",
            f"org.openjdk.jmh:jmh-generator-asm:{_JMH_VERSION}",
        ],
    )


@pytest.fixture
def jmh_lockfile(jmh_lockfile_def: JVMLockfileFixtureDefinition, request) -> JVMLockfileFixture:
    return jmh_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_hello_world_java(rule_runner: RuleRunner, jmh_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": jmh_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": jmh_lockfile.requirements_as_jvm_artifact_targets(),
            "example/BUILD": dedent(
                """\
                jmh_benchmarks(
                    name='example-java',
                    timeout=60,
                    dependencies=[
                        '3rdparty/jvm:org.openjdk.jmh_jmh-core',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-bytecode',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-reflection',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-asm',
                    ],
                )
                """
            ),
            "example/HelloWorldBenchmark.java": dedent(
                """\
                package example;

                import org.openjdk.jmh.annotations.Benchmark;

                public class HelloWorldBenchmark {

                    @Benchmark
                    public void wellHelloThere() {
                        // this method was intentionally left blank.
                    }

                }
                """
            ),
        }
    )

    bench_result = run_jmh_benchmark(
        rule_runner,
        "example",
        "example-java",
        "HelloWorldBenchmark.java",
    )

    assert bench_result.exit_code == 0
    assert bench_result.reports
    assert len(bench_result.reports.files) == 1

    report = _read_json_report(rule_runner, bench_result)
    assert len(report) == 1
    assert report[0]["jmhVersion"] == _JMH_VERSION
    assert report[0]["benchmark"] == "example.HelloWorldBenchmark.wellHelloThere"


@maybe_skip_jdk_test
def test_hello_world_kotlin(rule_runner: RuleRunner, jmh_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": jmh_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": jmh_lockfile.requirements_as_jvm_artifact_targets(),
            "example/BUILD": dedent(
                """\
                kotlin_jmh_benchmarks(
                    name='example-kotlin',
                    timeout=60,
                    dependencies=[
                        '3rdparty/jvm:org.openjdk.jmh_jmh-core',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-bytecode',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-reflection',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-asm',
                    ],
                )
                """
            ),
            "example/HelloWorldBenchmark.kt": dedent(
                """\
                package example

                import org.openjdk.jmh.annotations.Benchmark

                open class HelloWorldBenchmark {

                    @Benchmark
                    fun kotlinHelloThere() {
                        // this method was intentionally left blank.
                    }

                }
                """
            ),
        }
    )

    bench_result = run_jmh_benchmark(
        rule_runner,
        "example",
        "example-kotlin",
        "HelloWorldBenchmark.kt",
    )

    assert bench_result.exit_code == 0
    assert bench_result.reports
    assert len(bench_result.reports.files) == 1

    report = _read_json_report(rule_runner, bench_result)
    assert len(report) == 1
    assert report[0]["jmhVersion"] == _JMH_VERSION
    assert report[0]["benchmark"] == "example.HelloWorldBenchmark.kotlinHelloThere"


@maybe_skip_jdk_test
def test_hello_world_scala(rule_runner: RuleRunner, jmh_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": jmh_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": jmh_lockfile.requirements_as_jvm_artifact_targets(),
            "example/BUILD": dedent(
                """\
                scala_jmh_benchmarks(
                    name='example-scala',
                    timeout=60,
                    dependencies=[
                        '3rdparty/jvm:org.openjdk.jmh_jmh-core',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-bytecode',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-reflection',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-asm',
                    ],
                )
                """
            ),
            "example/HelloWorldBenchmark.scala": dedent(
                """\
                package example

                import org.openjdk.jmh.annotations.Benchmark

                class HelloWorldBenchmark {

                    @Benchmark
                    def kotlinHelloThere() {
                        // this method was intentionally left blank.
                    }

                }
                """
            ),
        }
    )

    bench_result = run_jmh_benchmark(
        rule_runner,
        "example",
        "example-scala",
        "HelloWorldBenchmark.scala",
    )

    assert bench_result.exit_code == 0
    assert bench_result.reports
    assert len(bench_result.reports.files) == 1

    report = _read_json_report(rule_runner, bench_result)
    assert len(report) == 1
    assert report[0]["jmhVersion"] == _JMH_VERSION
    assert report[0]["benchmark"] == "example.HelloWorldBenchmark.kotlinHelloThere"


def run_jmh_benchmark(
    rule_runner: RuleRunner,
    spec_path: str,
    target_name: str,
    relative_file_path: str,
) -> BenchmarkResult:
    jvm_options = ["-Djmh.ignoreLock=true"]
    jmh_args = ["-i", "1", "-f", "0", "-wi", "1", "-wf", "0", "-v", "extra"]
    args = [
        "--bench-timeouts",
        "--jmh-result-format=json",
        "--jmh-fail-on-error",
        f"--jmh-jvm-options={repr(jvm_options)}",
        f"--jmh-args={repr(jmh_args)}",
    ]
    rule_runner.set_options(args, env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(
        Address(spec_path=spec_path, target_name=target_name, relative_file_path=relative_file_path)
    )
    return rule_runner.request(
        BenchmarkResult, [JmhBenchmarkRequest.Batch("", (JmhBenchmarkFieldSet.create(tgt),), None)]
    )


def _read_json_report(rule_runner: RuleRunner, result: BenchmarkResult) -> list[dict[str, Any]]:
    assert result.reports
    contents = rule_runner.request(DigestContents, [result.reports.digest])
    assert len(contents) == 1

    return cast(list[dict[str, Any]], json.loads(contents[0].content))
