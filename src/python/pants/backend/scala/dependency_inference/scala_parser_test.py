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
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.target import SourcesField
from pants.jvm import jdk_rules
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.resolve import user_resolves
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *scala_parser.rules(),
            *user_resolves.rules(),
            *source_files.rules(),
            *jdk_rules.rules(),
            *target_types.rules(),
            *jvm_util_rules.rules(),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
            QueryRule(ScalaSourceDependencyAnalysis, (SourceFiles,)),
        ],
        target_types=[ScalaSourceTarget],
    )
    rule_runner.set_options(args=["-ldebug"], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def _analyze(rule_runner: RuleRunner, source: str) -> ScalaSourceDependencyAnalysis:
    rule_runner.write_files(
        {
            "BUILD": """scala_source(name="source", source="Source.scala")""",
            "Source.scala": source,
        }
    )

    target = rule_runner.get_target(address=Address("", target_name="source"))

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

    return rule_runner.request(ScalaSourceDependencyAnalysis, [source_files])


def test_parser_simple(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
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
                ScalaImport(name="foo.bar.SomeItem", alias=None, is_wildcard=False),
            ),
            "org.pantsbuild.example": (
                ScalaImport(
                    name="scala.collection.mutable.ArrayBuffer", alias=None, is_wildcard=False
                ),
                ScalaImport(
                    name="scala.collection.mutable.HashMap",
                    alias="RenamedHashMap",
                    is_wildcard=False,
                ),
                ScalaImport(name="java.io", alias=None, is_wildcard=True),
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
        "org.pantsbuild.+",
        "org.pantsbuild.ABaseClass",
        "org.pantsbuild.AParameterType",
        "org.pantsbuild.ATrait1",
        "org.pantsbuild.ATrait2.Nested",
        "org.pantsbuild.BaseWithConstructor",
        "org.pantsbuild.Integer",
        "org.pantsbuild.LambdaReturnType",
        "org.pantsbuild.LambdaTypeArg1",
        "org.pantsbuild.LambdaTypeArg2",
        "org.pantsbuild.OuterObject.NestedVal",
        "org.pantsbuild.SomeTypeInSecondaryConstructor",
        "org.pantsbuild.String",
        "org.pantsbuild.TupleTypeArg1",
        "org.pantsbuild.TupleTypeArg2",
        "org.pantsbuild.Unit",
        "org.pantsbuild.bar",
        "org.pantsbuild.foo",
    }


def test_extract_package_scopes(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
                package outer
                package more.than.one.part.at.once
                package inner
                """
        ),
    )

    assert sorted(analysis.scopes) == [
        "outer",
        "outer.more.than.one.part.at.once",
        "outer.more.than.one.part.at.once.inner",
    ]


def test_relative_import(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            import java.io
            import scala.{io => sio}
            import nada.{io => _}

            object OuterObject {
                import org.pantsbuild.{io => pio}

                val i = io.apply()
                val s = sio.apply()
                val p = pio.apply()
            }
            """
        ),
    )

    assert set(analysis.fully_qualified_consumed_symbols()) == {
        "io.apply",
        "java.io.apply",
        "org.pantsbuild.io.apply",
        "pio.apply",
        "scala.io.apply",
        "sio.apply",
    }


def test_package_object(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo
            package object bar {
              val Hello = "World"
            }
            """
        ),
    )
    assert sorted(analysis.provided_symbols) == ["foo.bar.Hello"]


def test_extract_annotations(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo

            @objectAnnotation("hello")
            object Object {
              @deprecated
              def foo(arg: String @argAnnotation("foo")): Unit = {}
            }

            @classAnnotation("world")
            class Class {
              @valAnnotation val foo = 3
              @varAnnotation var bar = 4
            }

            @traitAnnotation
            trait Trait {}
            """
        ),
    )
    assert sorted(analysis.fully_qualified_consumed_symbols()) == [
        "foo.String",
        "foo.Unit",
        "foo.classAnnotation",
        "foo.deprecated",
        "foo.objectAnnotation",
        "foo.traitAnnotation",
        "foo.valAnnotation",
        "foo.varAnnotation",
    ]
