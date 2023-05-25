# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.subsystems.jmh import Jmh
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JmhBenckmarksGeneratorTarget
from pants.backend.java.target_types import rules as java_target_types_rules
from pants.core.goals.bench import BenchmarkResult, get_filtered_environment
from pants.core.target_types import FilesGeneratorTarget, FileTarget, RelocatedFiles
from pants.core.util_rules import config_files, source_files, system_binaries, stripped_source_files
from pants.engine.addresses import Address, Addresses
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
            *java_target_types_rules(),
            *javac_rules(),
            *jmh_rules(),
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
        ],
    )
    return rule_runner


@pytest.fixture
def jmh_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "jmh.test.lock",
        [
            "org.openjdk.jmh:jmh-core:1.36",
            "org.openjdk.jmh:jmh-generator-bytecode:1.36",
            "org.openjdk.jmh:jmh-generator-reflection:1.36",
            "org.openjdk.jmh:jmh-generator-asm:1.36",
        ],
    )


@pytest.fixture
def jmh_lockfile(jmh_lockfile_def: JVMLockfileFixtureDefinition, request) -> JVMLockfileFixture:
    return jmh_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_hello_world(rule_runner: RuleRunner, jmh_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": jmh_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": jmh_lockfile.requirements_as_jvm_artifact_targets(),
            "BUILD": dedent(
                """\
                jmh_benchmarks(
                    name='example-bench',
                    dependencies=[
                        '3rdparty/jvm:org.openjdk.jmh_jmh-core',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-bytecode',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-reflection',
                        '3rdparty/jvm:org.openjdk.jmh_jmh-generator-asm',
                    ],
                )
                """
            ),
            "HelloWorldBenchmark.java": dedent(
                """\
                import org.openjdk.jmh.annotations.Benchmark;
                import org.openjdk.jmh.runner.Runner;
                import org.openjdk.jmh.runner.RunnerException;
                import org.openjdk.jmh.runner.options.Options;
                import org.openjdk.jmh.runner.options.OptionsBuilder;

                public class HelloWorldBenchmark {

                    @Benchmark
                    public void wellHelloThere() {
                        // this method was intentionally left blank.
                    }

                    /*
                    * ============================== HOW TO RUN THIS TEST: ====================================
                    *
                    * You are expected to see the run with large number of iterations, and
                    * very large throughput numbers. You can see that as the estimate of the
                    * harness overheads per method call. In most of our measurements, it is
                    * down to several cycles per call.
                    *
                    * a) Via command-line:
                    *    $ mvn clean install
                    *    $ java -jar target/benchmarks.jar JMHSample_01
                    *
                    * JMH generates self-contained JARs, bundling JMH together with it.
                    * The runtime options for the JMH are available with "-h":
                    *    $ java -jar target/benchmarks.jar -h
                    *
                    * b) Via the Java API:
                    *    (see the JMH homepage for possible caveats when running from IDE:
                    *      http://openjdk.java.net/projects/code-tools/jmh/)
                    */

                    public static void main(String[] args) throws RunnerException {
                        Options opt = new OptionsBuilder()
                                .include(JMHSample_01_HelloWorld.class.getSimpleName())
                                .forks(1)
                                .build();

                        new Runner(opt).run();
                    }

                }
                """
            ),
        }
    )

    bench_result = run_jmh_benchmark(rule_runner, "example-bench", "HelloWorldBenchmark.java")

    assert bench_result.exit_code == 0


def run_jmh_benchmark(
    rule_runner: RuleRunner, target_name: str, relative_file_path: str
) -> BenchmarkResult:
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(
        Address(spec_path="", target_name=target_name, relative_file_path=relative_file_path)
    )
    return rule_runner.request(
        BenchmarkResult, [JmhBenchmarkRequest.Batch("", (JmhBenchmarkFieldSet.create(tgt),), None)]
    )
