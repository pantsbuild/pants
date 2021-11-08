# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.scala import target_types
from pants.backend.scala.dependency_inference import scala_parser
from pants.backend.scala.dependency_inference.scala_parser import ScalaSourceDependencyAnalysis
from pants.backend.scala.target_types import ScalaSourceField, ScalaSourceTarget
from pants.build_graph.address import Address
from pants.core.util_rules import source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.target import SourcesField
from pants.jvm import jdk_rules
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmDependencyLockfile
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *scala_parser.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *jdk_rules.rules(),
            *target_types.rules(),
            *jvm_util_rules.rules(),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
            QueryRule(ScalaSourceDependencyAnalysis, (SourceFiles,)),
        ],
        target_types=[JvmDependencyLockfile, ScalaSourceTarget],
    )
    rule_runner.set_options(args=["-ldebug"], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def test_parser_simple(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": textwrap.dedent(
                """
            scala_source(
                name="simple-source",
                source="SimpleSource.scala",
            )
            """
            ),
            "SimpleSource.scala": textwrap.dedent(
                """
            package org.pantsbuild
            package example

            class OuterClass {
                val NestedVal = 3
                var NestedVar = "foo"
                trait NestedTrait {
                }
                class NestedClass {
                }
                type NestedType = Foo
                object NestedObject {
                }
            }

            trait OuterTrait {
                val NestedVal = 3
                var NestedVar = "foo"
                trait NestedTrait {
                }
                class NestedClass {
                }
                type NestedType = Foo
                object NestedObject {
                }
            }

            object OuterObject {
                val NestedVal = 3
                var NestedVar = "foo"
                trait NestedTrait {
                }
                class NestedClass {
                }
                type NestedType = Foo
                object NestedObject {
                }
            }
            """
            ),
        }
    )

    target = rule_runner.get_target(address=Address("", target_name="simple-source"))

    source_files = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                (target.get(SourcesField),),
                for_sources_types=(ScalaSourceField,),
                enable_codegen=True,
            )
        ],
    )

    analysis = rule_runner.request(
        ScalaSourceDependencyAnalysis,
        [source_files],
    )

    assert analysis.provided_names == FrozenOrderedSet(
        [
            "org.pantsbuild.example.OuterClass",
            "org.pantsbuild.example.OuterClass.NestedVal",
            "org.pantsbuild.example.OuterClass.NestedVar",
            "org.pantsbuild.example.OuterClass.NestedTrait",
            "org.pantsbuild.example.OuterClass.NestedClass",
            "org.pantsbuild.example.OuterClass.NestedType",
            "org.pantsbuild.example.OuterClass.NestedObject",
            "org.pantsbuild.example.OuterTrait",
            "org.pantsbuild.example.OuterTrait.NestedVal",
            "org.pantsbuild.example.OuterTrait.NestedVar",
            "org.pantsbuild.example.OuterTrait.NestedTrait",
            "org.pantsbuild.example.OuterTrait.NestedClass",
            "org.pantsbuild.example.OuterTrait.NestedType",
            "org.pantsbuild.example.OuterTrait.NestedObject",
            "org.pantsbuild.example.OuterObject",
            "org.pantsbuild.example.OuterObject.NestedVal",
            "org.pantsbuild.example.OuterObject.NestedVar",
            "org.pantsbuild.example.OuterObject.NestedTrait",
            "org.pantsbuild.example.OuterObject.NestedClass",
            "org.pantsbuild.example.OuterObject.NestedType",
            "org.pantsbuild.example.OuterObject.NestedObject",
        ]
    )
