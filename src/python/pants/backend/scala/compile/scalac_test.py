# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import JVMLockfileFixture
from pants.backend.scala.compile.scalac import CompileScalaSourceRequest
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.dependency_inference.rules import rules as scala_dep_inf_rules
from pants.backend.scala.goals.check import ScalacCheckRequest
from pants.backend.scala.goals.check import rules as scalac_check_rules
from pants.backend.scala.target_types import ScalacPluginTarget, ScalaSourcesGeneratorTarget
from pants.backend.scala.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.core.util_rules import source_files
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import FileDigest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import CoarsenedTargets
from pants.jvm import jdk_rules, testutil
from pants.jvm.compile import ClasspathEntry, CompileResult, FallibleClasspathEntry
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_test_util import TestCoursierWrapper
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
    maybe_skip_jdk_test,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner, logging


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *coursier_fetch_rules(),
            *jdk_rules.rules(),
            *scalac_check_rules(),
            *scalac_rules(),
            *source_files.rules(),
            *target_types_rules(),
            *testutil.rules(),
            *util_rules(),
            *scala_dep_inf_rules(),
            QueryRule(CheckResults, (ScalacCheckRequest,)),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(FallibleClasspathEntry, (CompileScalaSourceRequest,)),
            QueryRule(RenderedClasspath, (CompileScalaSourceRequest,)),
            QueryRule(ClasspathEntry, (CompileScalaSourceRequest,)),
        ],
        target_types=[JvmArtifactTarget, ScalaSourcesGeneratorTarget, ScalacPluginTarget],
    )
    rule_runner.set_options(
        args=["--scala-version-for-resolve={'jvm-default':'2.13.8'}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


scala_stdlib_jvm_lockfile = pytest.mark.jvm_lockfile(
    path="scala-library-2.13.test.lock", requirements=["org.scala-lang:scala-library:2.13.8"]
)


SCALA_LIB_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib

    class C {
        val hello = "hello!"
    }
    """
)

SCALA_LIB_JDK12_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib

    class C {
        val hello = "hello!".indent(4)
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


@maybe_skip_jdk_test
@scala_stdlib_jvm_lockfile
def test_compile_no_deps(rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'lib',
                )
                """
            ),
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
            "ExampleLib.scala": SCALA_LIB_SOURCE,
        }
    )
    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="", target_name="lib")
    )

    classpath = rule_runner.request(
        RenderedClasspath,
        [CompileScalaSourceRequest(component=coarsened_target, resolve=make_resolve(rule_runner))],
    )
    assert classpath.content == {
        ".ExampleLib.scala.lib.scalac.jar": {
            "META-INF/MANIFEST.MF",
            "org/pantsbuild/example/lib/C.class",
        }
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
    assert check_result.exit_code == 0


@maybe_skip_jdk_test
@scala_stdlib_jvm_lockfile
def test_compile_no_deps_jdk_12(rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'lib',
                    jdk = 'adopt:1.12',
                )
                """
            ),
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
            "ExampleLib.scala": SCALA_LIB_JDK12_SOURCE,
        }
    )
    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="", target_name="lib")
    )

    rule_runner.request(
        RenderedClasspath,
        [CompileScalaSourceRequest(component=coarsened_target, resolve=make_resolve(rule_runner))],
    )


@logging
@maybe_skip_jdk_test
@scala_stdlib_jvm_lockfile
def test_compile_jdk_12_file_fails_on_jdk_11(
    rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'lib',
                    jdk = 'adopt:1.11',
                )
                """
            ),
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
            "ExampleLib.scala": SCALA_LIB_JDK12_SOURCE,
        }
    )
    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="", target_name="lib")
    )

    with pytest.raises(ExecutionError):
        rule_runner.request(
            RenderedClasspath,
            [
                CompileScalaSourceRequest(
                    component=coarsened_target, resolve=make_resolve(rule_runner)
                )
            ],
        )


@logging
@maybe_skip_jdk_test
@scala_stdlib_jvm_lockfile
def test_compile_with_deps(rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture) -> None:
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
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
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
    classpath = rule_runner.request(
        RenderedClasspath,
        [
            CompileScalaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                ),
                resolve=make_resolve(rule_runner),
            )
        ],
    )
    assert classpath.content == {
        ".Example.scala.main.scalac.jar": {
            "META-INF/MANIFEST.MF",
            "org/pantsbuild/example/Main$.class",
            "org/pantsbuild/example/Main.class",
        }
    }


@maybe_skip_jdk_test
@scala_stdlib_jvm_lockfile
def test_compile_with_missing_dep_fails(
    rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture
) -> None:
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
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
        }
    )
    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert (
        "error: object lib is not a member of package org.pantsbuild.example"
        in fallible_result.stderr
    )


@maybe_skip_jdk_test
@pytest.mark.jvm_lockfile(
    path="joda-time.test.lock",
    requirements=[
        "joda-time:joda-time:2.10.10",
        "org.scala-lang:scala-library:2.13.8",
    ],
)
def test_compile_with_maven_deps(rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'main',
                    dependencies = ["3rdparty/jvm:joda-time_joda-time"],
                )
                """
            ),
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
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
    classpath = rule_runner.request(
        RenderedClasspath,
        [
            CompileScalaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                ),
                resolve=make_resolve(rule_runner),
            )
        ],
    )
    assert classpath.content == {
        ".Example.scala.main.scalac.jar": {
            "META-INF/MANIFEST.MF",
            "org/pantsbuild/example/Main$.class",
            "org/pantsbuild/example/Main.class",
        }
    }


@maybe_skip_jdk_test
@scala_stdlib_jvm_lockfile
def test_compile_with_undeclared_jvm_artifact_target_fails(
    rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'main',
                )
                """
            ),
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
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
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "error: object joda is not a member of package org" in fallible_result.stderr


@maybe_skip_jdk_test
@scala_stdlib_jvm_lockfile
def test_compile_with_undeclared_jvm_artifact_dependency_fails(
    rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture
) -> None:
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
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
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
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "error: object joda is not a member of package org" in fallible_result.stderr


acyclic_jvm_lockfile = pytest.mark.jvm_lockfile(
    path="acyclic.test.lock",
    requirements=[
        "com.lihaoyi:acyclic_2.13:0.2.1",
        "org.scala-lang:scala-library:2.13.8",
    ],
)


@maybe_skip_jdk_test
@acyclic_jvm_lockfile
def test_compile_with_scalac_plugin(
    rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "lib/BUILD": dedent(
                """\
                scalac_plugin(
                    name = "acyclic",
                    artifact = "3rdparty/jvm:com.lihaoyi_acyclic_2.13",
                )

                scala_sources(
                  dependencies=["3rdparty/jvm:com.lihaoyi_acyclic_2.13"],
                )
                """
            ),
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
            "lib/A.scala": dedent(
                """
                package lib
                import acyclic.file

                class A {
                  val b: B = null
                }
                """
            ),
            "lib/B.scala": dedent(
                """
                package lib

                class B {
                  val a: A = null
                }
                """
            ),
        }
    )
    rule_runner.set_options(
        args=[
            "--scala-version-for-resolve={'jvm-default': '2.13.8'}",
            "--scalac-plugins-for-resolve={'jvm-default': 'acyclic'}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="lib", relative_file_path="A.scala")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "error: Unwanted cyclic dependency" in fallible_result.stderr


@maybe_skip_jdk_test
@acyclic_jvm_lockfile
def test_compile_with_local_scalac_plugin(
    rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "lib/BUILD": dedent(
                """\
                scalac_plugin(
                    name = "acyclic",
                    artifact = "3rdparty/jvm:com.lihaoyi_acyclic_2.13",
                )

                scala_sources(
                    scalac_plugins=["acyclic"],
                )
                """
            ),
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
            "lib/A.scala": dedent(
                """
                package lib
                import acyclic.file

                class A {
                  val b: B = null
                }
                """
            ),
            "lib/B.scala": dedent(
                """
                package lib

                class B {
                  val a: A = null
                }
                """
            ),
        }
    )
    rule_runner.set_options(
        args=[
            "--scala-version-for-resolve={'jvm-default': '2.13.8'}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="lib", relative_file_path="A.scala")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "error: Unwanted cyclic dependency" in fallible_result.stderr


@maybe_skip_jdk_test
@pytest.mark.jvm_lockfile(
    path="multiple-scalac-plugins.test.lock",
    requirements=[
        "com.olegpy:better-monadic-for_2.13:0.3.1",
        "org.typelevel:kind-projector_2.13.8:0.13.2",
        "org.scala-lang:scala-compiler:2.13.8",
        "org.scala-lang:scala-library:2.13.8",
        "org.scala-lang:scala-reflect:2.13.8",
        "net.java.dev.jna:jna:5.3.1",
        "org.jline:jline:3.19.0",
    ],
)
def test_compile_with_multiple_scalac_plugins(
    rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "lib/BUILD": dedent(
                """\
                scala_sources()

                scalac_plugin(
                    name="kind-projector",
                    plugin_name="kind-projector",
                    artifact="3rdparty/jvm:org.typelevel_kind-projector_2.13.8",
                )

                scalac_plugin(
                    name="better-monadic-for",
                    plugin_name="bm4",
                    artifact="3rdparty/jvm:com.olegpy_better-monadic-for_2.13",
                )
                """
            ),
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
            "lib/A.scala": dedent(
                """\
                trait Functor[F[_]] {
                  def map[A, B](fa: F[A])(f: A => B): F[B]
                }

                object KindProjectorTest {
                  implicit def eitherFunctor[E]: Functor[Either[E, *]] = new Functor[Either[E, *]] {
                    def map[A, B](fa: Either[E, A])(f: A => B): Either[E, B] = {
                      fa match {
                        case Left(e) => Left(e)
                        case Right(a) => Right(f(a))
                      }
                    }
                  }
                }

                object BetterMonadicForTest {
                  def example: Option[String] = {
                    case class ImplicitTest(id: String)

                    for {
                      x <- Option(42)
                      implicit0(it: ImplicitTest) <- Option(ImplicitTest("eggs"))
                      _ <- Option("dummy")
                      _ = "dummy"
                      _ = assert(implicitly[ImplicitTest] eq it)
                    } yield "ok"
                  }
                }
                """
            ),
        }
    )
    rule_runner.set_options(
        args=[
            "--scala-version-for-resolve={'jvm-default': '2.13.8'}",
            "--scalac-plugins-for-resolve={'jvm-default': 'bm4,kind-projector'}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="lib", relative_file_path="A.scala")
        ),
        resolve=make_resolve(rule_runner),
    )
    rule_runner.request(RenderedClasspath, [request])


# TODO: This test demonstrates the limits of the current structure of the test lockfiles support: It
# needs multiple lockfiles, but `jvm_lockfile` is essentially a singleton because the relevant
# `pytest.mark.jvm_lockfile` can only be applied once. Separate fixture functions do not help, each with
# their own `pytest.mark.jvm_lockfile`, because those marks are ignored for fixture functions.
@maybe_skip_jdk_test
def test_compile_with_multiple_scala_versions(rule_runner: RuleRunner) -> None:
    scala_library_coord_2_12 = Coordinate(
        group="org.scala-lang", artifact="scala-library", version="2.12.15"
    )
    scala_library_coord_2_13 = Coordinate(
        group="org.scala-lang", artifact="scala-library", version="2.13.8"
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'main_2.12',
                    resolve = "scala2.12",
                )
                scala_sources(
                    name = 'main_2.13',
                    resolve = "scala2.13",
                )
                jvm_artifact(
                  name="org.scala-lang_scala-library_2.12.15",
                  group="org.scala-lang",
                  artifact="scala-library",
                  version="2.12.15",
                  resolve="scala2.12",
                )
                jvm_artifact(
                  name="org.scala-lang_scala-library_2.13.8",
                  group="org.scala-lang",
                  artifact="scala-library",
                  version="2.13.8",
                  resolve="scala2.13",
                )
                """
            ),
            "Example.scala": SCALA_LIB_SOURCE,
            "3rdparty/jvm/scala2.12.lock": TestCoursierWrapper.new(
                entries=(
                    CoursierLockfileEntry(
                        coord=scala_library_coord_2_12,
                        file_name="org.scala-lang_scala-library_2.12.15.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "e518bb640e2175de5cb1f8e326679b8d975376221f1b547757de429bbf4563f0",
                            5443542,
                        ),
                    ),
                ),
            ).serialize([ArtifactRequirement(scala_library_coord_2_12)]),
            "3rdparty/jvm/scala2.13.lock": TestCoursierWrapper.new(
                entries=(
                    CoursierLockfileEntry(
                        coord=scala_library_coord_2_13,
                        file_name="org.scala-lang_scala-library_2.13.8.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "a0882b82514190c2bac7d1a459872a75f005fc0f3e88b2bc0390367146e35db7",
                            6003601,
                        ),
                    ),
                ),
            ).serialize([ArtifactRequirement(scala_library_coord_2_13)]),
        }
    )
    rule_runner.set_options(
        [
            '--scala-version-for-resolve={"scala2.12":"2.12.15","scala2.13":"2.13.8"}',
            '--jvm-resolves={"scala2.12":"3rdparty/jvm/scala2.12.lock","scala2.13":"3rdparty/jvm/scala2.13.lock"}',
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    classpath_2_12 = rule_runner.request(
        ClasspathEntry,
        [
            CompileScalaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main_2.12")
                ),
                resolve=make_resolve(rule_runner, "scala2.12", "3rdparty/jvm/scala2.12.lock"),
            )
        ],
    )
    entries_2_12 = list(ClasspathEntry.closure([classpath_2_12]))
    filenames_2_12 = sorted(
        itertools.chain.from_iterable(entry.filenames for entry in entries_2_12)
    )
    assert filenames_2_12 == [
        ".Example.scala.main_2.12.scalac.jar",
        "org.scala-lang_scala-library_2.12.15.jar",
    ]

    classpath_2_13 = rule_runner.request(
        ClasspathEntry,
        [
            CompileScalaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main_2.13")
                ),
                resolve=make_resolve(rule_runner, "scala2.13", "3rdparty/jvm/scala2.13.lock"),
            )
        ],
    )
    entries_2_13 = list(ClasspathEntry.closure([classpath_2_13]))
    filenames_2_13 = sorted(
        itertools.chain.from_iterable(entry.filenames for entry in entries_2_13)
    )
    assert filenames_2_13 == [
        ".Example.scala.main_2.13.scalac.jar",
        "org.scala-lang_scala-library_2.13.8.jar",
    ]
