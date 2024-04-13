# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference import symbol_mapper as java_symbol_mapper
from pants.backend.java.dependency_inference.rules import rules as java_dep_inference_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JavaSourceTarget
from pants.backend.java.target_types import rules as java_target_rules
from pants.backend.scala import target_types as scala_target_types
from pants.backend.scala.dependency_inference import rules as scala_dep_inference_rules
from pants.backend.scala.dependency_inference import scala_parser
from pants.backend.scala.dependency_inference import symbol_mapper as scala_symbol_mapper
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.core.util_rules import config_files, source_files, system_binaries
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import QueryRule
from pants.engine.target import Dependencies, DependenciesRequest
from pants.jvm.jdk_rules import rules as java_util_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.strip_jar import strip_jar
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *jvm_tool.rules(),
            *java_dep_inference_rules(),
            *java_target_rules(),
            *java_util_rules(),
            *strip_jar.rules(),
            *javac_rules(),
            *java_symbol_mapper.rules(),
            *source_files.rules(),
            *scala_parser.rules(),
            *scala_symbol_mapper.rules(),
            *scala_dep_inference_rules.rules(),
            *scala_target_types.rules(),
            *system_binaries.rules(),
            *util_rules(),
            QueryRule(Addresses, (DependenciesRequest,)),
        ],
        target_types=[
            JavaSourcesGeneratorTarget,
            JavaSourceTarget,
            ScalaSourcesGeneratorTarget,
            ScalaSourceTarget,
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def test_java_infers_scala_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "org/pantsbuild/lib/BUILD": "scala_sources()\n",
            "org/pantsbuild/lib/Foo.scala": textwrap.dedent(
                """
                package org.pantsbuild.lib

                object Foo {
                  def grok(): Unit = {
                    println("Hello world!")
                  }
                }
                """
            ),
            "org/pantsbuild/example/BUILD": "java_sources()\n",
            "org/pantsbuild/example/Bar.java": textwrap.dedent(
                """
                package org.pantsbuild.example;

                import org.pantsbuild.lib.Foo$;

                public class Bar {
                  public static void main(String[] args) {
                    Foo$.MODULE$.grok();
                  }
                }
                """
            ),
        }
    )
    example_tgt = rule_runner.get_target(
        Address("org/pantsbuild/example", target_name="example", relative_file_path="Bar.java")
    )
    deps = rule_runner.request(Addresses, [DependenciesRequest(example_tgt[Dependencies])])
    assert deps == Addresses(
        [Address("org/pantsbuild/lib", target_name="lib", relative_file_path="Foo.scala")]
    )
