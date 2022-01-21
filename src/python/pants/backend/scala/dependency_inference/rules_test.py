# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.scala.dependency_inference import scala_parser, symbol_mapper
from pants.backend.scala.dependency_inference.rules import InferScalaSourceDependencies
from pants.backend.scala.dependency_inference.rules import rules as dep_inference_rules
from pants.backend.scala.target_types import ScalaSourceField, ScalaSourcesGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_rules
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferredDependencies,
    Targets,
)
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve import user_resolves
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *user_resolves.rules(),
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

    assert (
        rule_runner.request(
            InferredDependencies,
            [InferScalaSourceDependencies(target_a[ScalaSourceField])],
        )
        == InferredDependencies(dependencies=[])
    )

    assert (
        rule_runner.request(
            InferredDependencies,
            [InferScalaSourceDependencies(target_b[ScalaSourceField])],
        )
        == InferredDependencies(dependencies=[])
    )


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
        InferredDependencies, [InferScalaSourceDependencies(target_a[ScalaSourceField])]
    ) == InferredDependencies(dependencies=[target_b.address])

    assert rule_runner.request(
        InferredDependencies, [InferScalaSourceDependencies(target_b[ScalaSourceField])]
    ) == InferredDependencies(dependencies=[target_a.address])


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
        InferredDependencies, [InferScalaSourceDependencies(target_b[ScalaSourceField])]
    ) == InferredDependencies(dependencies=[])
    assert len(caplog.records) == 1
    assert (
        "The target b/B.scala imports `org.pantsbuild.a.A`, but Pants cannot safely" in caplog.text
    )

    assert rule_runner.request(
        InferredDependencies, [InferScalaSourceDependencies(target_c[ScalaSourceField])]
    ) == InferredDependencies(dependencies=[Address("a_one", relative_file_path="A.scala")])


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
        InferredDependencies, [InferScalaSourceDependencies(tgt[ScalaSourceField])]
    )
    assert deps == InferredDependencies([Address("bar", relative_file_path="B.scala")])
