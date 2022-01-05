# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.scala.compile.scalac import CompileScalaSourceRequest
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.goals.check import ScalacCheckRequest
from pants.backend.scala.goals.check import rules as scalac_check_rules
from pants.backend.scala.target_types import ScalacPluginTarget, ScalaSourcesGeneratorTarget
from pants.backend.scala.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.core.util_rules import source_files
from pants.engine.addresses import Addresses
from pants.engine.fs import FileDigest
from pants.engine.target import CoarsenedTargets
from pants.jvm import jdk_rules, testutil
from pants.jvm.compile import CompileResult, FallibleClasspathEntry
from pants.jvm.resolve.coursier_fetch import (
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
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
            *coursier_setup_rules(),
            *jdk_rules.rules(),
            *scalac_check_rules(),
            *scalac_rules(),
            *source_files.rules(),
            *target_types_rules(),
            *testutil.rules(),
            *util_rules(),
            QueryRule(CheckResults, (ScalacCheckRequest,)),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(FallibleClasspathEntry, (CompileScalaSourceRequest,)),
            QueryRule(RenderedClasspath, (CompileScalaSourceRequest,)),
        ],
        target_types=[JvmArtifactTarget, ScalaSourcesGeneratorTarget, ScalacPluginTarget],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
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
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(()).to_json().decode(),
            "ExampleLib.scala": SCALA_LIB_SOURCE,
        }
    )
    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="", target_name="lib")
    )

    print(coarsened_target)

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
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(()).to_json().decode(),
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
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(()).to_json().decode(),
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
            "3rdparty/jvm/default.lock": resolved_joda_lockfile.to_json().decode(),
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
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(()).to_json().decode("utf-8"),
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
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(()).to_json().decode(),
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
def test_compile_with_scalac_plugin(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "lib/BUILD": dedent(
                """\
                jvm_artifact(
                    name = "acyclic_lib",
                    group = "com.lihaoyi",
                    artifact = "acyclic_2.13",
                    version = "0.2.1",
                    packages=["acyclic.**"],
                )

                scalac_plugin(
                    name = "acyclic",
                    artifact = ":acyclic_lib",
                )

                scala_sources(
                  dependencies=[':acyclic_lib'],
                )
                """
            ),
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(
                entries=(
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="com.lihaoyi", artifact="acyclic_2.13", version="0.2.1"
                        ),
                        file_name="acyclic_2.13-0.2.1.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "4bc4656140ad5e4802fedcdbe920ec7c92dbebf5e76d1c60d35676a314481944",
                            62534,
                        ),
                    ),
                )
            )
            .to_json()
            .decode("utf-8"),
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
            "--scalac-plugins-global=lib:acyclic",
            "--scalac-plugins-global-lockfile=3rdparty/jvm/default.lock",
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
def test_compile_with_multiple_scalac_plugins(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "lib/BUILD": dedent(
                """\
                scala_sources()

                jvm_artifact(
                    name="kind-projector-lib",
                    group="org.typelevel",
                    artifact="kind-projector_2.13.6",
                    version="0.13+",
                )

                scalac_plugin(
                    name="kind-projector",
                    plugin_name="kind-projector",
                    artifact=":kind-projector-lib",
                )

                jvm_artifact(
                    name="better-monadic-for-lib",
                    group="com.olegpy",
                    artifact="better-monadic-for_2.13",
                    version="0.3+",
                )

                scalac_plugin(
                    name="better-monadic-for",
                    plugin_name="bm4",
                    artifact=":better-monadic-for-lib",
                )
                """
            ),
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(
                entries=(
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="com.olegpy",
                            artifact="better-monadic-for_2.13",
                            version="0.3.1",
                            packaging="jar",
                            strict=True,
                        ),
                        file_name="com.olegpy_better-monadic-for_2.13_0.3.1.jar",
                        direct_dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-compiler",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-library",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                            ]
                        ),
                        dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-compiler",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-library",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                            ]
                        ),
                        file_digest=FileDigest(
                            "fac649fa7de697d1f98d3f814c4b70f5372c547fa41778383e22cee6c16084f5",
                            130370,
                        ),
                        remote_url=None,
                        pants_address=None,
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="net.java.dev.jna",
                            artifact="jna",
                            version="5.3.1",
                            packaging="jar",
                            strict=True,
                        ),
                        file_name="net.java.dev.jna_jna_5.3.1.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "01cb505c0698d0f7acf3524c7e73acb7dc424a5bae5e9c86ce44075ab32bc4ee",
                            1505196,
                        ),
                        remote_url=None,
                        pants_address=None,
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.jline",
                            artifact="jline",
                            version="3.19.0",
                            packaging="jar",
                            strict=True,
                        ),
                        file_name="org.jline_jline_3.19.0.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "c99ddcfa5431cab88d1cd40fd63bec6ab5a3fe2e83877051198539af66592a46",
                            987021,
                        ),
                        remote_url=None,
                        pants_address=None,
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.scala-lang",
                            artifact="scala-compiler",
                            version="2.13.6",
                            packaging="jar",
                            strict=True,
                        ),
                        file_name="org.scala-lang_scala-compiler_2.13.6.jar",
                        direct_dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="net.java.dev.jna",
                                    artifact="jna",
                                    version="5.3.1",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.jline",
                                    artifact="jline",
                                    version="3.19.0",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-library",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-reflect",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                            ]
                        ),
                        dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="net.java.dev.jna",
                                    artifact="jna",
                                    version="5.3.1",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.jline",
                                    artifact="jline",
                                    version="3.19.0",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-library",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-reflect",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                            ]
                        ),
                        file_digest=FileDigest(
                            "310d263d622a3d016913e94ee00b119d270573a5ceaa6b21312d69637fd9eec1",
                            12010571,
                        ),
                        remote_url=None,
                        pants_address=None,
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.scala-lang",
                            artifact="scala-library",
                            version="2.13.6",
                            packaging="jar",
                            strict=True,
                        ),
                        file_name="org.scala-lang_scala-library_2.13.6.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "f19ed732e150d3537794fd3fe42ee18470a3f707efd499ecd05a99e727ff6c8a",
                            5955737,
                        ),
                        remote_url=None,
                        pants_address=None,
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.scala-lang",
                            artifact="scala-reflect",
                            version="2.13.6",
                            packaging="jar",
                            strict=True,
                        ),
                        file_name="org.scala-lang_scala-reflect_2.13.6.jar",
                        direct_dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-library",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                )
                            ]
                        ),
                        dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-library",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                )
                            ]
                        ),
                        file_digest=FileDigest(
                            "f713593809b387c60935bb9a940dfcea53bd0dbf8fdc8d10739a2896f8ac56fa",
                            3769997,
                        ),
                        remote_url=None,
                        pants_address=None,
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.typelevel",
                            artifact="kind-projector_2.13.6",
                            version="0.13.2",
                            packaging="jar",
                            strict=True,
                        ),
                        file_name="org.typelevel_kind-projector_2.13.6_0.13.2.jar",
                        direct_dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-compiler",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-library",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                            ]
                        ),
                        dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-compiler",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-reflect",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.scala-lang",
                                    artifact="scala-library",
                                    version="2.13.6",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="net.java.dev.jna",
                                    artifact="jna",
                                    version="5.3.1",
                                    packaging="jar",
                                    strict=True,
                                ),
                                Coordinate(
                                    group="org.jline",
                                    artifact="jline",
                                    version="3.19.0",
                                    packaging="jar",
                                    strict=True,
                                ),
                            ]
                        ),
                        file_digest=FileDigest(
                            "3d713d02bbe0d52b01c22ac11a50970460114f32b339f3ea429d52461d6c39ff",
                            44257,
                        ),
                        remote_url=None,
                        pants_address=None,
                    ),
                )
            )
            .to_json()
            .decode("utf-8"),
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
            "--scalac-plugins-global=['lib:better-monadic-for', 'lib:kind-projector']",
            "--scalac-plugins-global-lockfile=3rdparty/jvm/default.lock",
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
