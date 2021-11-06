# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.scala.compile.scalac import CompileScalaSourceRequest
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.goals.check import ScalacCheckRequest
from pants.backend.scala.goals.check import rules as scalac_check_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget
from pants.backend.scala.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.core.util_rules import source_files
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, FileDigest, PathGlobs
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, Targets
from pants.jvm import jdk_rules, testutil
from pants.jvm.compile import CompiledClassfiles, CompileResult, FallibleCompiledClassfiles
from pants.jvm.resolve.coursier_fetch import (
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    CoursierResolveKey,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmArtifact, JvmDependencyLockfile
from pants.jvm.testutil import RenderedClasspath, maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner, logging

NAMED_RESOLVE_OPTIONS = '--jvm-resolves={"test": "coursier_resolve.lockfile"}'
DEFAULT_RESOLVE_OPTION = "--jvm-default-resolve=test"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *jdk_rules.rules(),
            *scalac_check_rules(),
            *scalac_rules(),
            *source_files.rules(),
            *target_types_rules(),
            *testutil.rules(),
            *util_rules(),
            QueryRule(CheckResults, (ScalacCheckRequest,)),
            QueryRule(FallibleCompiledClassfiles, (CompileScalaSourceRequest,)),
            QueryRule(CompiledClassfiles, (CompileScalaSourceRequest,)),
            QueryRule(CoarsenedTargets, (Addresses,)),
        ],
        target_types=[JvmDependencyLockfile, ScalaSourcesGeneratorTarget, JvmArtifact],
    )
    rule_runner.set_options(
        args=[
            NAMED_RESOLVE_OPTIONS,
            DEFAULT_RESOLVE_OPTION,
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


SCALA_LIB_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib

    class C {
        val hello = "hello!"
    }
    """
)

SCALA_LIB_MAIN_SOURCE = dedent(
    """
    package org.pantsbuild.example

    import org.pantsbuild.example.lib.C

    object Main {
        def main(args: Array[String]): Unit = {
            val c = new C()
            println(c.hello)
        }
    }
    """
)


def expect_single_expanded_coarsened_target(
    rule_runner: RuleRunner, address: Address
) -> CoarsenedTarget:
    expanded_target = rule_runner.request(Targets, [Addresses([address])]).expect_single()
    coarsened_targets = rule_runner.request(
        CoarsenedTargets, [Addresses([expanded_target.address])]
    )
    assert len(coarsened_targets) == 1
    return coarsened_targets[0]


def make_resolve(
    rule_runner: RuleRunner,
    resolve_name: str = "test",
    resolve_path: str = "coursier_resolve.lockfile",
) -> CoursierResolveKey:
    digest = rule_runner.request(Digest, [PathGlobs([resolve_path])])
    return CoursierResolveKey(name=resolve_name, path=resolve_path, digest=digest)


@logging
@maybe_skip_jdk_test
def test_compile_no_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'lib',
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "ExampleLib.scala": SCALA_LIB_SOURCE,
        }
    )
    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="", target_name="lib")
    )

    print(coarsened_target)

    compiled_classfiles = rule_runner.request(
        CompiledClassfiles,
        [CompileScalaSourceRequest(component=coarsened_target, resolve=make_resolve(rule_runner))],
    )

    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {
        ".ExampleLib.scala.lib.jar": {"META-INF/MANIFEST.MF", "org/pantsbuild/example/lib/C.class"}
    }

    # Additionally validate that `check` works.
    check_results = rule_runner.request(
        CheckResults,
        [
            ScalacCheckRequest(
                [ScalacCheckRequest.field_set_type.create(coarsened_target.representative)]
            )
        ],
    )

    assert len(check_results.results) == 1
    check_result = check_results.results[0]
    assert check_result.partition_description == str(coarsened_target)


@logging
@maybe_skip_jdk_test
def test_compile_with_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'main',
                    dependencies = [
                        'lib:lib',
                    ]
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "Example.scala": SCALA_LIB_MAIN_SOURCE,
            "lib/BUILD": dedent(
                """\
                scala_sources(
                    name = 'lib',
                )
                """
            ),
            "lib/ExampleLib.scala": SCALA_LIB_SOURCE,
        }
    )
    compiled_classfiles = rule_runner.request(
        CompiledClassfiles,
        [
            CompileScalaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                ),
                resolve=make_resolve(rule_runner),
            )
        ],
    )
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {
        ".Example.scala.main.jar": {
            "META-INF/MANIFEST.MF",
            "org/pantsbuild/example/Main$.class",
            "org/pantsbuild/example/Main.class",
        }
    }


@maybe_skip_jdk_test
@logging
def test_compile_with_missing_dep_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'main',
                )
                """
            ),
            "Example.scala": SCALA_LIB_MAIN_SOURCE,
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
        }
    )
    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleCompiledClassfiles, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert (
        "error: object lib is not a member of package org.pantsbuild.example"
        in fallible_result.stderr
    )


@maybe_skip_jdk_test
@logging
def test_compile_with_maven_deps(rule_runner: RuleRunner) -> None:
    resolved_joda_lockfile = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(group="joda-time", artifact="joda-time", version="2.10.10"),
                file_name="joda-time-2.10.10.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="dd8e7c92185a678d1b7b933f31209b6203c8ffa91e9880475a1be0346b9617e3",
                    serialized_bytes_length=644419,
                ),
            ),
        )
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = "joda-time_joda-time",
                    group = "joda-time",
                    artifact = "joda-time",
                    version = "2.10.10",
                )
                scala_sources(
                    name = 'main',
                    dependencies = [":joda-time_joda-time"],
                )
                """
            ),
            "coursier_resolve.lockfile": resolved_joda_lockfile.to_json().decode("utf-8"),
            "Example.scala": dedent(
                """
                package org.pantsbuild.example

                import org.joda.time.DateTime

                object Main {
                    def main(args: Array[String]): Unit = {
                        val dt = new DateTime()
                        println(dt.getYear)
                    }
                }
                """
            ),
        }
    )
    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        ),
        resolve=make_resolve(rule_runner),
    )
    compiled_classfiles = rule_runner.request(CompiledClassfiles, [request])
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {
        ".Example.scala.main.jar": {
            "META-INF/MANIFEST.MF",
            "org/pantsbuild/example/Main$.class",
            "org/pantsbuild/example/Main.class",
        }
    }


@maybe_skip_jdk_test
def test_compile_with_undeclared_jvm_artifact_target_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'main',
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "Example.scala": dedent(
                """
                package org.pantsbuild.example

                import org.joda.time.DateTime

                object Main {
                    def main(args: Array[String]): Unit = {
                        val dt = new DateTime()
                        println(dt.getYear)
                    }
                }
                """
            ),
        }
    )

    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleCompiledClassfiles, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "error: object joda is not a member of package org" in fallible_result.stderr


@maybe_skip_jdk_test
def test_compile_with_undeclared_jvm_artifact_dependency_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = "joda-time_joda-time",
                    group = "joda-time",
                    artifact = "joda-time",
                    version = "2.10.10",
                )
                scala_sources(
                    name = 'main',
                    dependencies = [],  # `joda-time` needs to be here for compile to succeed
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "Example.scala": dedent(
                """
                package org.pantsbuild.example

                import org.joda.time.DateTime

                object Main {
                    def main(args: Array[String]): Unit = {
                        val dt = new DateTime()
                        println(dt.getYear)
                    }
                }
                """
            ),
        }
    )

    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleCompiledClassfiles, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "error: object joda is not a member of package org" in fallible_result.stderr
