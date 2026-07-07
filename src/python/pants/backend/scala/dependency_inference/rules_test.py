# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.scala.dependency_inference import scala_parser, symbol_mapper
from pants.backend.scala.dependency_inference.rules import (
    InferScalaSourceDependencies,
    ScalaSourceDependenciesInferenceFieldSet,
)
from pants.backend.scala.dependency_inference.rules import rules as dep_inference_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_rules
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.internals.parametrize import Parametrize
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferredDependencies,
    Targets,
)
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *jvm_tool.rules(),
            *dep_inference_rules(),
            *scala_parser.rules(),
            *symbol_mapper.rules(),
            *scala_target_rules(),
            *source_files.rules(),
            *util_rules(),
            *jdk_rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(ExplicitlyProvidedDependencies, [DependenciesRequest]),
            QueryRule(InferredDependencies, [InferScalaSourceDependencies]),
            QueryRule(Targets, [UnparsedAddressInputs]),
        ],
        target_types=[ScalaSourcesGeneratorTarget],
        objects={"parametrize": Parametrize},
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_infer_scala_imports_same_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 't',
                )
                """
            ),
            "A.scala": dedent(
                """\
                package org.pantsbuild.a

                object A {}
                """
            ),
            "B.scala": dedent(
                """\
                package org.pantsbuild.b

                object B {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="t", relative_file_path="A.scala"))
    target_b = rule_runner.get_target(Address("", target_name="t", relative_file_path="B.scala"))

    assert rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([])

    assert rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([])


@maybe_skip_jdk_test
def test_infer_scala_imports_with_cycle(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'a',
                )
                """
            ),
            "A.scala": dedent(
                """\
                package org.pantsbuild.a

                import org.pantsbuild.b.B

                class A {}
                """
            ),
            "sub/BUILD": dedent(
                """\
                scala_sources(
                    name = 'b',
                )
                """
            ),
            "sub/B.scala": dedent(
                """\
                package org.pantsbuild.b

                import org.pantsbuild.a.A

                class B {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="a", relative_file_path="A.scala"))
    target_b = rule_runner.get_target(Address("sub", target_name="b", relative_file_path="B.scala"))

    assert rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([target_b.address])

    assert rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([target_a.address])


@maybe_skip_jdk_test
def test_infer_java_imports_ambiguous(rule_runner: RuleRunner, caplog) -> None:
    ambiguous_source = dedent(
        """\
                package org.pantsbuild.a
                class A {}
                """
    )
    rule_runner.write_files(
        {
            "a_one/BUILD": "scala_sources()",
            "a_one/A.scala": ambiguous_source,
            "a_two/BUILD": "scala_sources()",
            "a_two/A.scala": ambiguous_source,
            "b/BUILD": "scala_sources()",
            "b/B.scala": dedent(
                """\
                package org.pantsbuild.b
                import org.pantsbuild.a.A
                class B {}
                """
            ),
            "c/BUILD": dedent(
                """\
                scala_sources(
                  dependencies=["!a_two/A.scala"],
                )
                """
            ),
            "c/C.scala": dedent(
                """\
                package org.pantsbuild.c
                import org.pantsbuild.a.A
                class C {}
                """
            ),
        }
    )
    target_b = rule_runner.get_target(Address("b", relative_file_path="B.scala"))
    target_c = rule_runner.get_target(Address("c", relative_file_path="C.scala"))

    # Because there are two sources of `org.pantsbuild.a.A`, neither should be inferred for B. But C
    # disambiguates with a `!`, and so gets the appropriate version.
    caplog.clear()
    assert rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([])
    assert len(caplog.records) == 1
    assert (
        "The target b/B.scala imports `org.pantsbuild.a.A`, but Pants cannot safely" in caplog.text
    )

    assert rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(target_c))],
    ) == InferredDependencies([Address("a_one", relative_file_path="A.scala")])


def test_infer_unqualified_symbol_from_intermediate_scope(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "scala_sources()",
            "foo/A.scala": dedent(
                """\
                package org.pantsbuild.outer
                package intermediate

                object A {
                  def main(args: Array[String]): Unit = {
                    println(B.Foo)
                  }
                }
                """
            ),
            "bar/BUILD": "scala_sources()",
            "bar/B.scala": dedent(
                """\
                package org.pantsbuild.outer
                object B {
                  val Foo = 3
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo", relative_file_path="A.scala"))
    deps = rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(tgt))],
    )
    assert deps == InferredDependencies([Address("bar", relative_file_path="B.scala")])


def test_overlapping_package_unambiguous(rule_runner: RuleRunner) -> None:
    # Test that declaring a `type` alias inside of a `package object` is unambiguous with a
    # `class`/`object` of the same name in another file.
    rule_runner.write_files(
        {
            "foo/BUILD": "scala_sources()",
            "foo/A.scala": dedent(
                """\
                package org.pantsbuild.foo

                import org.pantsbuild.bar.Bar

                object A {
                  def main(args: Array[String]): Unit = {
                    println(Bar.Bar)
                  }
                }
                """
            ),
            "bar/BUILD": "scala_sources()",
            "bar/package.scala": dedent(
                """\
                package org.pantsbuild

                package object bar {
                  type Bar = String
                }
                """
            ),
            "bar/B.scala": dedent(
                """\
                package org.pantsbuild.bar
                object Bar {
                  val Bar = 3
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo", relative_file_path="A.scala"))
    deps = rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(tgt))],
    )
    assert deps == InferredDependencies(
        [
            Address("bar", relative_file_path="package.scala"),
            Address("bar", relative_file_path="B.scala"),
        ]
    )


@maybe_skip_jdk_test
def test_multi_resolve_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "lib/BUILD": dedent(
                """\
            scala_sources(resolve=parametrize("scala-2.13", "scala-2.12"))
            """
            ),
            "lib/Library.scala": dedent(
                """\
            package org.pantsbuild.lib

            object Library {
              def grok(): Unit = {
                println("Hello world!")
              }
            }
            """
            ),
            "user/BUILD": dedent(
                """\
            scala_sources(resolve=parametrize("scala-2.13", "scala-2.12"))
            """
            ),
            "user/Main.scala": dedent(
                """\
            package org.pantsbuild.user

            import org.pantsbuild.lib.Library

            object Main {
              def main(args: Array[String]): Unit = {
                Library.grok()
              }
            }
            """
            ),
        }
    )
    rule_runner.set_options(
        [
            '--jvm-resolves={"scala-2.13":"3rdparty/jvm/scala-2.13.lock", "scala-2.12":"3rdparty/jvm/scala-2.12.lock"}'
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    tgt = rule_runner.get_target(
        Address("user", relative_file_path="Main.scala", parameters={"resolve": "scala-2.13"})
    )
    deps = rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(tgt))],
    )
    assert deps == InferredDependencies(
        [Address("lib", relative_file_path="Library.scala", parameters={"resolve": "scala-2.13"})]
    )

    tgt = rule_runner.get_target(
        Address("user", relative_file_path="Main.scala", parameters={"resolve": "scala-2.12"})
    )
    deps = rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(tgt))],
    )
    assert deps == InferredDependencies(
        [Address("lib", relative_file_path="Library.scala", parameters={"resolve": "scala-2.12"})]
    )


@maybe_skip_jdk_test
def test_recursive_objects(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "A/BUILD": dedent(
                """\
                scala_sources(name = "a")
                """
            ),
            "A/A.scala": dedent(
                """\
                package org.pantsbuild.a

                object A {
                    def funA(): Int = ???
                }
                """
            ),
            "B/BUILD": dedent(
                """\
                scala_sources(name = "b")
                """
            ),
            "B/B.scala": dedent(
                """\
                package org.pantsbuild.b

                import org.pantsbuild.a.A

                object B extends A {
                    def funB(): Int = ???
                }
                """
            ),
            "C/BUILD": dedent(
                """\
                scala_sources(name = "c")
                """
            ),
            "C/C.scala": dedent(
                """\
                package org.pantsbuild.c

                import org.pantsbuild.b.B.funA

                class C {
                    val x = funA()
                }
                """
            ),
            "D/BUILD": dedent(
                """\
                scala_sources(name = "d")
                """
            ),
            "D/D.scala": dedent(
                """\
                package org.pantsbuild.d

                import org.pantsbuild.b.B.funB

                class D {
                    val x = funB()
                }
                """
            ),
        }
    )

    target_b = rule_runner.get_target(Address("B", target_name="b", relative_file_path="B.scala"))
    target_c = rule_runner.get_target(Address("C", target_name="c", relative_file_path="C.scala"))
    target_d = rule_runner.get_target(Address("D", target_name="d", relative_file_path="D.scala"))

    assert rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(target_c))],
    ) == InferredDependencies([target_b.address])

    assert rule_runner.request(
        InferredDependencies,
        [InferScalaSourceDependencies(ScalaSourceDependenciesInferenceFieldSet.create(target_d))],
    ) == InferredDependencies([target_b.address])
