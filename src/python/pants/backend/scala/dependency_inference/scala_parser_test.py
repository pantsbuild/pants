# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.scala import target_types
from pants.backend.scala.dependency_inference import scala_parser
from pants.backend.scala.dependency_inference.scala_parser import (
    AnalyzeScalaSourceRequest,
    ScalaImport,
    ScalaProvidedSymbol,
    ScalaSourceDependencyAnalysis,
)
from pants.backend.scala.target_types import ScalaSourceField, ScalaSourceTarget
from pants.backend.scala.util_rules import versions
from pants.build_graph.address import Address
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine import process
from pants.engine.target import SourcesField
from pants.jvm import jdk_rules
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.resolve import jvm_tool
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *scala_parser.rules(),
            *jvm_tool.rules(),
            *source_files.rules(),
            *jdk_rules.rules(),
            *target_types.rules(),
            *jvm_util_rules.rules(),
            *process.rules(),
            *versions.rules(),
            QueryRule(AnalyzeScalaSourceRequest, (SourceFilesRequest,)),
            QueryRule(ScalaSourceDependencyAnalysis, (AnalyzeScalaSourceRequest,)),
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

    request = rule_runner.request(
        AnalyzeScalaSourceRequest,
        [
            SourceFilesRequest(
                (target.get(SourcesField),),
                for_sources_types=(ScalaSourceField,),
                enable_codegen=True,
            )
        ],
    )

    return rule_runner.request(ScalaSourceDependencyAnalysis, [request])


def test_parser_simple(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package org.pantsbuild
            package example

            import scala.collection.mutable.{ArrayBuffer, HashMap => RenamedHashMap}
            import java.io._
            import anotherPackage.calc

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

                def a(a: TraitConsumedType): Integer
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

            object ApplyQualifier {
                def func4(a: Integer) = calc.calcFunc(a).toInt
            }
            """
        ),
    )

    assert sorted(symbol.name for symbol in analysis.provided_symbols) == [
        "org.pantsbuild.example.ASubClass",
        "org.pantsbuild.example.ASubTrait",
        "org.pantsbuild.example.ApplyQualifier",
        "org.pantsbuild.example.ApplyQualifier.func4",
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

    assert sorted(symbol.name for symbol in analysis.provided_symbols_encoded) == [
        "org.pantsbuild.example.ASubClass",
        "org.pantsbuild.example.ASubTrait",
        "org.pantsbuild.example.ApplyQualifier",
        "org.pantsbuild.example.ApplyQualifier$",
        "org.pantsbuild.example.ApplyQualifier$.MODULE$",
        "org.pantsbuild.example.ApplyQualifier.func4",
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
                ScalaImport(name="anotherPackage.calc", alias=None, is_wildcard=False),
            ),
        }
    )

    assert analysis.consumed_symbols_by_scope == FrozenDict(
        {
            "org.pantsbuild.example.OuterClass.NestedObject": FrozenOrderedSet(["String"]),
            "org.pantsbuild.example.OuterObject": FrozenOrderedSet(["Foo"]),
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
                    "OuterObject",
                    "bar",
                    "OuterObject.NestedVal",
                ]
            ),
            "org.pantsbuild.example.HasPrimaryConstructor": FrozenOrderedSet(
                ["bar", "SomeTypeInSecondaryConstructor"]
            ),
            "org.pantsbuild.example.OuterClass": FrozenOrderedSet(["Foo"]),
            "org.pantsbuild.example.ApplyQualifier": FrozenOrderedSet(
                ["Integer", "a", "toInt", "calc.calcFunc", "calc"]
            ),
            "org.pantsbuild.example.OuterTrait": FrozenOrderedSet(
                ["Integer", "TraitConsumedType", "Foo"]
            ),
            "org.pantsbuild.example": FrozenOrderedSet(
                [
                    "ABaseClass",
                    "ATrait1",
                    "SomeTypeInPrimaryConstructor",
                    "foo",
                    "ATrait2.Nested",
                    "BaseWithConstructor",
                ]
            ),
        }
    )

    assert set(analysis.fully_qualified_consumed_symbols()) == {
        # Because they contain dots, and thus might be fully qualified. See #13545.
        "ATrait2.Nested",
        "OuterObject.NestedVal",
        "anotherPackage.calc.calcFunc",
        "calc.calcFunc",
        # Because of the wildcard import.
        "java.io.+",
        "java.io.ABaseClass",
        "java.io.AParameterType",
        "java.io.ATrait1",
        "java.io.ATrait2.Nested",
        "java.io.BaseWithConstructor",
        "java.io.Foo",
        "java.io.OuterObject.NestedVal",
        "java.io.OuterObject",
        "java.io.SomeTypeInPrimaryConstructor",
        "java.io.String",
        "java.io.TraitConsumedType",
        "java.io.Unit",
        "java.io.a",
        "java.io.Integer",
        "java.io.LambdaReturnType",
        "java.io.LambdaTypeArg1",
        "java.io.LambdaTypeArg2",
        "java.io.SomeTypeInSecondaryConstructor",
        "java.io.bar",
        "java.io.calc",
        "java.io.calc.calcFunc",
        "java.io.foo",
        "java.io.toInt",
        "java.io.TupleTypeArg1",
        "java.io.TupleTypeArg2",
        # Because it's the top-most scope in the file.
        "org.pantsbuild.example.+",
        "org.pantsbuild.example.ABaseClass",
        "org.pantsbuild.example.AParameterType",
        "org.pantsbuild.example.BaseWithConstructor",
        "org.pantsbuild.example.Foo",
        "org.pantsbuild.example.Integer",
        "org.pantsbuild.example.SomeTypeInSecondaryConstructor",
        "org.pantsbuild.example.ATrait1",
        "org.pantsbuild.example.ATrait2.Nested",
        "org.pantsbuild.example.OuterObject.NestedVal",
        "org.pantsbuild.example.SomeTypeInPrimaryConstructor",
        "org.pantsbuild.example.String",
        "org.pantsbuild.example.TraitConsumedType",
        "org.pantsbuild.example.Unit",
        "org.pantsbuild.example.a",
        "org.pantsbuild.example.bar",
        "org.pantsbuild.example.calc",
        "org.pantsbuild.example.calc.calcFunc",
        "org.pantsbuild.example.foo",
        "org.pantsbuild.example.toInt",
        "org.pantsbuild.example.LambdaReturnType",
        "org.pantsbuild.example.LambdaTypeArg1",
        "org.pantsbuild.example.LambdaTypeArg2",
        "org.pantsbuild.example.OuterObject",
        "org.pantsbuild.example.TupleTypeArg1",
        "org.pantsbuild.example.TupleTypeArg2",
        "org.pantsbuild.+",
        "org.pantsbuild.ABaseClass",
        "org.pantsbuild.AParameterType",
        "org.pantsbuild.ATrait1",
        "org.pantsbuild.ATrait2.Nested",
        "org.pantsbuild.BaseWithConstructor",
        "org.pantsbuild.Foo",
        "org.pantsbuild.Integer",
        "org.pantsbuild.LambdaReturnType",
        "org.pantsbuild.LambdaTypeArg1",
        "org.pantsbuild.LambdaTypeArg2",
        "org.pantsbuild.OuterObject",
        "org.pantsbuild.OuterObject.NestedVal",
        "org.pantsbuild.SomeTypeInPrimaryConstructor",
        "org.pantsbuild.SomeTypeInSecondaryConstructor",
        "org.pantsbuild.String",
        "org.pantsbuild.TraitConsumedType",
        "org.pantsbuild.TupleTypeArg1",
        "org.pantsbuild.TupleTypeArg2",
        "org.pantsbuild.Unit",
        "org.pantsbuild.a",
        "org.pantsbuild.bar",
        "org.pantsbuild.calc",
        "org.pantsbuild.calc.calcFunc",
        "org.pantsbuild.foo",
        "org.pantsbuild.toInt",
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
        "io",
        "io.apply",
        "java.io.apply",
        "org.pantsbuild.io.apply",
        "pio",
        "pio.apply",
        "scala.io.apply",
        "sio",
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
    assert sorted(symbol.name for symbol in analysis.provided_symbols) == [
        "foo.bar",
        "foo.bar.Hello",
    ]


def test_source3(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        args=[
            "-ldebug",
            "--scala-version-for-resolve={'jvm-default':'2.13.8'}",
            "--scalac-args=['-Xsource:3']",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo

            import bar.*
            """
        ),
    )
    assert analysis.imports_by_scope.get("foo") == (ScalaImport("bar", None, True),)


def test_extract_annotations(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo

            @objectAnnotation("hello", SomeType)
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
        "foo.SomeType",
        "foo.String",
        "foo.Unit",
        "foo.classAnnotation",
        "foo.deprecated",
        "foo.objectAnnotation",
        "foo.traitAnnotation",
        "foo.valAnnotation",
        "foo.varAnnotation",
    ]


def test_type_arguments(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo

            object Object {
              var a: A[SomeType] = ???
              val b: B[AnotherType] = ???
            }
            """
        ),
    )
    assert sorted(analysis.fully_qualified_consumed_symbols()) == [
        "foo.???",
        "foo.A",
        "foo.AnotherType",
        "foo.B",
        "foo.SomeType",
    ]


def test_recursive_objects(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo

            object Bar {
                def a = ???
            }

            object Foo extends Bar {
                def b = ???
            }
            """
        ),
    )

    assert sorted(analysis.provided_symbols, key=lambda s: s.name) == [
        ScalaProvidedSymbol("foo.Bar", False),
        ScalaProvidedSymbol("foo.Bar.a", False),
        ScalaProvidedSymbol("foo.Foo", True),
    ]


def test_object_extends_ctor(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo

            import example._

            object Foo extends Bar(hello) {
            }
            """
        ),
    )

    assert sorted(analysis.fully_qualified_consumed_symbols()) == [
        "example.Bar",
        "example.hello",
        "foo.Bar",
        "foo.hello",
    ]


def test_package_object_extends_trait(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo

            package object bar extends Trait {
            }
            """
        ),
    )

    assert sorted(analysis.fully_qualified_consumed_symbols()) == ["foo.Trait", "foo.bar.Trait"]


def test_enum(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        args=[
            "-ldebug",
            "--scala-version-for-resolve={'jvm-default':'3.3.0'}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo
            enum Spam {
                case Ham
                case Eggs
            }
            """
        ),
    )

    expected_symbols = [
        ScalaProvidedSymbol("foo.Spam", False),
        ScalaProvidedSymbol("foo.Spam.Eggs", False),
        ScalaProvidedSymbol("foo.Spam.Ham", False),
    ]

    assert sorted(analysis.provided_symbols, key=lambda x: x.name) == expected_symbols


def test_enum_use(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        args=[
            "-ldebug",
            "--scala-version-for-resolve={'jvm-default':'3.3.0'}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """
            package foo
            enum Spam {
                case Ham(x: Eggs)
            }
            """
        ),
    )
    assert sorted(analysis.fully_qualified_consumed_symbols()) == ["foo.Eggs"]


def test_types_at_toplevel_package(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """\
            trait Foo

            class Bar

            object Quxx
            """
        ),
    )

    expected_symbols = [
        ScalaProvidedSymbol("Foo", False),
        ScalaProvidedSymbol("Bar", False),
        ScalaProvidedSymbol("Quxx", False),
    ]

    expected_symbols_encoded = expected_symbols.copy()
    expected_symbols_encoded.extend(
        [ScalaProvidedSymbol("Quxx$", False), ScalaProvidedSymbol("Quxx$.MODULE$", False)]
    )

    def by_name(symbol: ScalaProvidedSymbol) -> str:
        return symbol.name

    assert analysis.provided_symbols == FrozenOrderedSet(sorted(expected_symbols, key=by_name))
    assert analysis.provided_symbols_encoded == FrozenOrderedSet(
        sorted(expected_symbols_encoded, key=by_name)
    )


def test_type_constraint(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """\
            package foo

            trait Foo[T >: A <: B]

            class Bar[T >: C <: D]

            class Quxx {
                def doSomething[T >: E <: F]() = ()
            }
            """
        ),
    )

    assert sorted(analysis.fully_qualified_consumed_symbols()) == [
        "foo.A",
        "foo.B",
        "foo.C",
        "foo.D",
        "foo.E",
        "foo.F",
    ]


def test_type_context_bounds(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """\
            package foo

            class Foo[F[_] : Functor]

            class Bar {
                def doSomething[F[_] : Applicative]() = ()
            }
            """
        ),
    )

    assert sorted(analysis.fully_qualified_consumed_symbols()) == [
        "foo.Applicative",
        "foo.Functor",
    ]
