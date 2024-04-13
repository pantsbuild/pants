# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.kotlin.dependency_inference import kotlin_parser, symbol_mapper
from pants.backend.kotlin.dependency_inference.rules import (
    InferKotlinSourceDependencies,
    KotlinSourceDependenciesInferenceFieldSet,
)
from pants.backend.kotlin.dependency_inference.rules import rules as dep_inference_rules
from pants.backend.kotlin.target_types import KotlinSourcesGeneratorTarget
from pants.backend.kotlin.target_types import rules as kotlin_target_type_rules
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.internals.parametrize import Parametrize
from pants.engine.rules import QueryRule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferredDependencies,
    Targets,
)
from pants.jvm import jdk_rules
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference import symbol_mapper as jvm_symbol_mapper
from pants.jvm.resolve import jvm_tool
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as jvm_util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *jvm_tool.rules(),
            *dep_inference_rules(),
            *kotlin_parser.rules(),
            *symbol_mapper.rules(),
            *kotlin_target_type_rules(),
            *source_files.rules(),
            *jvm_util_rules(),
            *jdk_rules.rules(),
            *artifact_mapper.rules(),
            *jvm_symbol_mapper.rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(ExplicitlyProvidedDependencies, [DependenciesRequest]),
            QueryRule(InferredDependencies, [InferKotlinSourceDependencies]),
            QueryRule(Targets, [UnparsedAddressInputs]),
        ],
        target_types=[KotlinSourcesGeneratorTarget],
        objects={"parametrize": Parametrize},
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_infer_kotlin_imports_same_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(name = 't')
                """
            ),
            "A.kt": dedent(
                """\
                package org.pantsbuild.a

                class A {}
                """
            ),
            "B.kt": dedent(
                """\
                package org.pantsbuild.b

                class B {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="t", relative_file_path="A.kt"))
    target_b = rule_runner.get_target(Address("", target_name="t", relative_file_path="B.kt"))

    assert rule_runner.request(
        InferredDependencies,
        [InferKotlinSourceDependencies(KotlinSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([])

    assert rule_runner.request(
        InferredDependencies,
        [InferKotlinSourceDependencies(KotlinSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([])


@maybe_skip_jdk_test
def test_infer_kotlin_imports_with_cycle(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(name = 'a')
                """
            ),
            "A.kt": dedent(
                """\
                package org.pantsbuild.a

                import org.pantsbuild.b.B

                class A {}
                """
            ),
            "sub/BUILD": dedent(
                """\
                kotlin_sources(name = 'b',)
                """
            ),
            "sub/B.kt": dedent(
                """\
                package org.pantsbuild.b

                import org.pantsbuild.a.A

                class B {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="a", relative_file_path="A.kt"))
    target_b = rule_runner.get_target(Address("sub", target_name="b", relative_file_path="B.kt"))

    assert rule_runner.request(
        InferredDependencies,
        [InferKotlinSourceDependencies(KotlinSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([target_b.address])

    assert rule_runner.request(
        InferredDependencies,
        [InferKotlinSourceDependencies(KotlinSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([target_a.address])


@maybe_skip_jdk_test
def test_infer_kotlin_imports_ambiguous(rule_runner: RuleRunner, caplog) -> None:
    ambiguous_source = dedent(
        """\
        package org.pantsbuild.a
        class A {}
        """
    )
    rule_runner.write_files(
        {
            "a_one/BUILD": "kotlin_sources()",
            "a_one/A.kt": ambiguous_source,
            "a_two/BUILD": "kotlin_sources()",
            "a_two/A.kt": ambiguous_source,
            "b/BUILD": "kotlin_sources()",
            "b/B.kt": dedent(
                """\
                package org.pantsbuild.b
                import org.pantsbuild.a.A
                class B {}
                """
            ),
            "c/BUILD": dedent(
                """\
                kotlin_sources(
                  dependencies=["!a_two/A.kt"],
                )
                """
            ),
            "c/C.kt": dedent(
                """\
                package org.pantsbuild.c
                import org.pantsbuild.a.A
                class C {}
                """
            ),
        }
    )
    target_b = rule_runner.get_target(Address("b", relative_file_path="B.kt"))
    target_c = rule_runner.get_target(Address("c", relative_file_path="C.kt"))

    # Because there are two sources of `org.pantsbuild.a.A`, neither should be inferred for B. But C
    # disambiguates with a `!`, and so gets the appropriate version.
    caplog.clear()
    assert rule_runner.request(
        InferredDependencies,
        [InferKotlinSourceDependencies(KotlinSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([])
    assert len(caplog.records) == 1
    assert "The target b/B.kt imports `org.pantsbuild.a.A`, but Pants cannot safely" in caplog.text

    assert rule_runner.request(
        InferredDependencies,
        [InferKotlinSourceDependencies(KotlinSourceDependenciesInferenceFieldSet.create(target_c))],
    ) == InferredDependencies([Address("a_one", relative_file_path="A.kt")])


@maybe_skip_jdk_test
def test_infer_same_package_via_consumed_symbol(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(name = 'a')
                """
            ),
            "A.kt": dedent(
                """\
                package org.pantsbuild.kotlin.example

                class A {
                  def grok() {}
                }
                """
            ),
            "Main.kt": dedent(
                """\
                package org.pantsbuild.kotlin.example

                def main(args: Array<String>) {
                  val a = A()
                  a.grok()
                }
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="a", relative_file_path="A.kt"))
    target_main = rule_runner.get_target(Address("", target_name="a", relative_file_path="Main.kt"))

    assert rule_runner.request(
        InferredDependencies,
        [InferKotlinSourceDependencies(KotlinSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([])

    assert rule_runner.request(
        InferredDependencies,
        [
            InferKotlinSourceDependencies(
                KotlinSourceDependenciesInferenceFieldSet.create(target_main)
            )
        ],
    ) == InferredDependencies([target_a.address])
