# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.scala import target_types
from pants.backend.scala.dependency_inference import scala_parser
from pants.backend.scala.dependency_inference.scala_parser import (
    ScalaImport,
    ScalaSourceDependencyAnalysis,
)
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
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner, logging
from pants.util.frozendict import FrozenDict
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


@logging
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

            import scala.collection.mutable.{ArrayBuffer, HashMap => RenamedHashMap}
            import java.io._

            class OuterClass {
                import foo.bar.SomeItem

                val NestedVal = 3
                var NestedVar = "foo"
                trait NestedTrait {
                }
                class NestedClass {
                }
                type NestedType = Foo
                object NestedObject {
                  val valWithType: String = "foo"
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

            object Functions {
              def func1(a: Integer, b: AParameterType): Unit = {
                val a = foo + 5
                val b = bar(5, "hello") + OuterObject.NestedVal
              }
              def func2: (TupleTypeArg1, TupleTypeArg2) = {}
              def func3: (LambdaTypeArg1, LambdaTypeArg2) => LambdaReturnType = {}
            }

            class ASubClass extends ABaseClass with ATrait1 with ATrait2.Nested { }
            trait ASubTrait extends ATrait1 with ATrait2.Nested { }

            class HasPrimaryConstructor(foo: SomeTypeInPrimaryConstructor) extends BaseWithConstructor(foo) {
               def this(bar: SomeTypeInSecondaryConstructor) {
                 this(bar)
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

    assert sorted(list(analysis.provided_symbols)) == [
        "org.pantsbuild.example.ASubClass",
        "org.pantsbuild.example.ASubTrait",
        "org.pantsbuild.example.Functions",
        "org.pantsbuild.example.Functions.func1",
        "org.pantsbuild.example.Functions.func2",
        "org.pantsbuild.example.Functions.func3",
        "org.pantsbuild.example.HasPrimaryConstructor",
        "org.pantsbuild.example.OuterClass",
        "org.pantsbuild.example.OuterClass.NestedClass",
        "org.pantsbuild.example.OuterClass.NestedObject",
        "org.pantsbuild.example.OuterClass.NestedObject.valWithType",
        "org.pantsbuild.example.OuterClass.NestedTrait",
        "org.pantsbuild.example.OuterClass.NestedType",
        "org.pantsbuild.example.OuterClass.NestedVal",
        "org.pantsbuild.example.OuterClass.NestedVar",
        "org.pantsbuild.example.OuterObject",
        "org.pantsbuild.example.OuterObject.NestedClass",
        "org.pantsbuild.example.OuterObject.NestedObject",
        "org.pantsbuild.example.OuterObject.NestedTrait",
        "org.pantsbuild.example.OuterObject.NestedType",
        "org.pantsbuild.example.OuterObject.NestedVal",
        "org.pantsbuild.example.OuterObject.NestedVar",
        "org.pantsbuild.example.OuterTrait",
        "org.pantsbuild.example.OuterTrait.NestedClass",
        "org.pantsbuild.example.OuterTrait.NestedObject",
        "org.pantsbuild.example.OuterTrait.NestedTrait",
        "org.pantsbuild.example.OuterTrait.NestedType",
        "org.pantsbuild.example.OuterTrait.NestedVal",
        "org.pantsbuild.example.OuterTrait.NestedVar",
    ]

    assert sorted(list(analysis.provided_symbols_encoded)) == [
        "org.pantsbuild.example.ASubClass",
        "org.pantsbuild.example.ASubTrait",
        "org.pantsbuild.example.Functions",
        "org.pantsbuild.example.Functions$",
        "org.pantsbuild.example.Functions$.MODULE$",
        "org.pantsbuild.example.Functions.func1",
        "org.pantsbuild.example.Functions.func2",
        "org.pantsbuild.example.Functions.func3",
        "org.pantsbuild.example.HasPrimaryConstructor",
        "org.pantsbuild.example.OuterClass",
        "org.pantsbuild.example.OuterClass.NestedClass",
        "org.pantsbuild.example.OuterClass.NestedObject",
        "org.pantsbuild.example.OuterClass.NestedObject$",
        "org.pantsbuild.example.OuterClass.NestedObject$.MODULE$",
        "org.pantsbuild.example.OuterClass.NestedObject.valWithType",
        "org.pantsbuild.example.OuterClass.NestedTrait",
        "org.pantsbuild.example.OuterClass.NestedType",
        "org.pantsbuild.example.OuterClass.NestedVal",
        "org.pantsbuild.example.OuterClass.NestedVar",
        "org.pantsbuild.example.OuterObject",
        "org.pantsbuild.example.OuterObject$",
        "org.pantsbuild.example.OuterObject$.MODULE$",
        "org.pantsbuild.example.OuterObject.NestedClass",
        "org.pantsbuild.example.OuterObject.NestedObject",
        "org.pantsbuild.example.OuterObject.NestedObject$",
        "org.pantsbuild.example.OuterObject.NestedObject$.MODULE$",
        "org.pantsbuild.example.OuterObject.NestedTrait",
        "org.pantsbuild.example.OuterObject.NestedType",
        "org.pantsbuild.example.OuterObject.NestedVal",
        "org.pantsbuild.example.OuterObject.NestedVar",
        "org.pantsbuild.example.OuterTrait",
        "org.pantsbuild.example.OuterTrait.NestedClass",
        "org.pantsbuild.example.OuterTrait.NestedObject",
        "org.pantsbuild.example.OuterTrait.NestedObject$",
        "org.pantsbuild.example.OuterTrait.NestedObject$.MODULE$",
        "org.pantsbuild.example.OuterTrait.NestedTrait",
        "org.pantsbuild.example.OuterTrait.NestedType",
        "org.pantsbuild.example.OuterTrait.NestedVal",
        "org.pantsbuild.example.OuterTrait.NestedVar",
    ]

    assert analysis.imports_by_scope == FrozenDict(
        {
            "org.pantsbuild.example.OuterClass": (
                ScalaImport(name="foo.bar.SomeItem", is_wildcard=False),
            ),
            "org.pantsbuild.example": (
                ScalaImport(name="scala.collection.mutable.ArrayBuffer", is_wildcard=False),
                ScalaImport(name="scala.collection.mutable.HashMap", is_wildcard=False),
                ScalaImport(name="java.io", is_wildcard=True),
            ),
        }
    )

    assert analysis.consumed_symbols_by_scope == FrozenDict(
        {
            "org.pantsbuild.example.OuterClass.NestedObject": FrozenOrderedSet(["String"]),
            "org.pantsbuild.example.Functions": FrozenOrderedSet(
                [
                    "TupleTypeArg2",
                    "foo",
                    "TupleTypeArg1",
                    "LambdaReturnType",
                    "+",
                    "Unit",
                    "Integer",
                    "LambdaTypeArg2",
                    "AParameterType",
                    "LambdaTypeArg1",
                    "bar",
                    "OuterObject.NestedVal",
                ]
            ),
            "org.pantsbuild.example.HasPrimaryConstructor": FrozenOrderedSet(
                ["bar", "SomeTypeInSecondaryConstructor"]
            ),
            "org.pantsbuild.example": FrozenOrderedSet(
                ["ABaseClass", "ATrait1", "ATrait2.Nested", "BaseWithConstructor"]
            ),
        }
    )

    assert set(analysis.fully_qualified_consumed_symbols()) == {
        # Because they contain dots, and thus might be fully qualified. See #13545.
        "ATrait2.Nested",
        "OuterObject.NestedVal",
        # Because of the wildcard import.
        "java.io.+",
        "java.io.ABaseClass",
        "java.io.AParameterType",
        "java.io.ATrait1",
        "java.io.ATrait2.Nested",
        "java.io.BaseWithConstructor",
        "java.io.OuterObject.NestedVal",
        "java.io.String",
        "java.io.Unit",
        "java.io.Integer",
        "java.io.LambdaReturnType",
        "java.io.LambdaTypeArg1",
        "java.io.LambdaTypeArg2",
        "java.io.SomeTypeInSecondaryConstructor",
        "java.io.bar",
        "java.io.foo",
        "java.io.TupleTypeArg1",
        "java.io.TupleTypeArg2",
        # Because it's the top-most scope in the file.
        "org.pantsbuild.example.+",
        "org.pantsbuild.example.ABaseClass",
        "org.pantsbuild.example.AParameterType",
        "org.pantsbuild.example.BaseWithConstructor",
        "org.pantsbuild.example.Integer",
        "org.pantsbuild.example.SomeTypeInSecondaryConstructor",
        "org.pantsbuild.example.ATrait1",
        "org.pantsbuild.example.ATrait2.Nested",
        "org.pantsbuild.example.OuterObject.NestedVal",
        "org.pantsbuild.example.String",
        "org.pantsbuild.example.Unit",
        "org.pantsbuild.example.bar",
        "org.pantsbuild.example.foo",
        "org.pantsbuild.example.LambdaReturnType",
        "org.pantsbuild.example.LambdaTypeArg1",
        "org.pantsbuild.example.LambdaTypeArg2",
        "org.pantsbuild.example.TupleTypeArg1",
        "org.pantsbuild.example.TupleTypeArg2",
    }
