# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.dependency_inference.java_parser import (
    FallibleJavaSourceDependencyAnalysisResult,
)
from pants.backend.java.dependency_inference.java_parser import rules as java_parser_rules
from pants.backend.java.dependency_inference.types import JavaImport, JavaSourceDependencyAnalysis
from pants.backend.java.target_types import JavaSourceField, JavaSourceTarget
from pants.build_graph.address import Address
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import ProcessExecutionFailure
from pants.engine.target import SourcesField
from pants.jvm import jdk_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *jvm_tool.rules(),
            *java_parser_rules(),
            *source_files.rules(),
            *util_rules(),
            *jdk_rules.rules(),
            QueryRule(FallibleJavaSourceDependencyAnalysisResult, (SourceFiles,)),
            QueryRule(JavaSourceDependencyAnalysis, (SourceFiles,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[JavaSourceTarget],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_simple_java_parser_analysis(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_source(
                    name='simple-source',
                    source='SimpleSource.java',
                )
                """
            ),
            "SimpleSource.java": dedent(
                """
                package org.pantsbuild.example;

                import java.util.Date;
                import bogus.*;
                import static bogus.T;
                import bogus.T.t;
                import static bogus.Foo.*;

                public class SimpleSource {
                    public void hello() {
                        System.out.println("hello");
                        Date date = new Date();
                        System.out.println("It's " + date.toString());
                        some.qualified.ref.Foo.bar();
                        some.other.Thing[] things = new some.other.Thing[1];

                        var result = switch("TEST") {
                            case "TEST" -> {
                                yield "something";
                            }
                            default -> "something else";
                        };
                        System.out.println("It's " + result);
                    }
                }

                sealed interface SimpleInterface permits SimpleImplementation1 {}

                final class SimpleImplementation1 implements SimpleInterface {}

                sealed class SimpleClass permits SimpleImplementation2 {}

                final class SimpleImplementation2 implements SimpleClass {}

                class Foo {}
                """
            ),
        }
    )

    target = rule_runner.get_target(address=Address(spec_path="", target_name="simple-source"))

    source_files = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                (target.get(SourcesField),),
                for_sources_types=(JavaSourceField,),
                enable_codegen=True,
            )
        ],
    )

    analysis = rule_runner.request(
        JavaSourceDependencyAnalysis,
        [source_files],
    )
    assert analysis.declared_package == "org.pantsbuild.example"
    assert analysis.imports == (
        JavaImport(name="java.util.Date"),
        JavaImport(name="bogus", is_asterisk=True),
        JavaImport(name="bogus.T", is_static=True),
        JavaImport(name="bogus.T.t"),
        JavaImport(name="bogus.Foo", is_asterisk=True, is_static=True),
    )
    assert analysis.top_level_types == (
        "org.pantsbuild.example.SimpleSource",
        "org.pantsbuild.example.SimpleInterface",
        "org.pantsbuild.example.SimpleImplementation1",
        "org.pantsbuild.example.SimpleClass",
        "org.pantsbuild.example.SimpleImplementation2",
        "org.pantsbuild.example.Foo",
    )
    assert sorted(analysis.consumed_types) == [
        "Date",
        "SimpleClass",
        "SimpleInterface",
        "System",
        "date",  # note: false positive on a variable identifier
        "some",
        "some.other.Thing",
    ]


@maybe_skip_jdk_test
def test_java_parser_fallible_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_source(
                    name='simple-source',
                    source='SimpleSource.java',
                )
                """
            ),
            "SimpleSource.java": dedent(
                """
                syntax error!
                """
            ),
        }
    )

    target = rule_runner.get_target(address=Address(spec_path="", target_name="simple-source"))

    source_files = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                (target.get(SourcesField),),
                for_sources_types=(JavaSourceField,),
                enable_codegen=True,
            )
        ],
    )

    fallible_result = rule_runner.request(
        FallibleJavaSourceDependencyAnalysisResult,
        [source_files],
    )
    assert fallible_result.process_result.exit_code != 0

    with pytest.raises(ExecutionError) as exc_info:
        rule_runner.request(
            JavaSourceDependencyAnalysis,
            [source_files],
        )
    assert isinstance(exc_info.value.wrapped_exceptions[0], ProcessExecutionFailure)


@maybe_skip_jdk_test
def test_java_parser_unnamed_package(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_source(
                    name='simple-source',
                    source='SimpleSource.java',
                )
                """
            ),
            "SimpleSource.java": dedent(
                """
                public class SimpleSource {
                    public void hello() {
                        System.out.println("hello");
                    }
                }

                class Foo {}
                """
            ),
        }
    )

    target = rule_runner.get_target(address=Address(spec_path="", target_name="simple-source"))

    source_files = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                (target.get(SourcesField),),
                for_sources_types=(JavaSourceField,),
                enable_codegen=True,
            )
        ],
    )

    analysis = rule_runner.request(JavaSourceDependencyAnalysis, [source_files])
    assert analysis.declared_package is None
    assert analysis.imports == ()
    assert analysis.top_level_types == ("SimpleSource", "Foo")
    assert analysis.consumed_types == ("System",)


@maybe_skip_jdk_test
def test_java_parser_consumed_types(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_source(
                    name='source',
                    source='SomeUnqualifiedTypes.java',
                )
                """
            ),
            "SomeUnqualifiedTypes.java": dedent(
                """
                package org.pantsbuild.test;

                @ClassAnnotation
                public class AnImpl implements SomeInterface {
                    @InnerClassAnnotation
                    public static class Inner extends SomeGeneric<String> {
                    }

                    @FieldAnnotation
                    Provided provided = provided;

                    public AnImpl(Provider<SomeThing> provider) {
                        this.provided = provider.provide();
                    }

                    @Override
                    public int foo() throws AThrownException {
                        StaticClassRef.someMethod();
                        return 2;
                    }
                }
                """
            ),
        }
    )

    target = rule_runner.get_target(address=Address(spec_path="", target_name="source"))

    source_files = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                (target.get(SourcesField),),
                for_sources_types=(JavaSourceField,),
                enable_codegen=True,
            )
        ],
    )

    analysis = rule_runner.request(JavaSourceDependencyAnalysis, [source_files])
    assert analysis.declared_package == "org.pantsbuild.test"
    assert analysis.imports == ()
    assert analysis.top_level_types == ("org.pantsbuild.test.AnImpl",)
    assert sorted(analysis.consumed_types) == [
        "AThrownException",
        "ClassAnnotation",
        "FieldAnnotation",
        "InnerClassAnnotation",
        "Override",
        "Provided",
        "Provider",
        "SomeGeneric",
        "SomeInterface",
        "SomeThing",
        "StaticClassRef",
        "String",
        "provider",  # note: false positive on a variable identifier
    ]
