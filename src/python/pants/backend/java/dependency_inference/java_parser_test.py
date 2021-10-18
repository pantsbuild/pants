# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.java_parser import (
    FallibleJavaSourceDependencyAnalysisResult,
)
from pants.backend.java.dependency_inference.java_parser import rules as java_parser_rules
from pants.backend.java.dependency_inference.java_parser_launcher import (
    rules as java_parser_launcher_rules,
)
from pants.backend.java.dependency_inference.types import JavaImport, JavaSourceDependencyAnalysis
from pants.backend.java.target_types import JavaSourceField, JavaSourceTarget
from pants.build_graph.address import Address
from pants.core.util_rules import source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import ProcessExecutionFailure
from pants.engine.target import SourcesField
from pants.jvm import jdk_rules
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmDependencyLockfile
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *java_parser_launcher_rules(),
            *java_parser_rules(),
            *javac_rules(),
            *source_files.rules(),
            *util_rules(),
            *jdk_rules.rules(),
            QueryRule(FallibleJavaSourceDependencyAnalysisResult, (SourceFiles,)),
            QueryRule(JavaSourceDependencyAnalysis, (SourceFiles,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[JvmDependencyLockfile, JavaSourceTarget],
    )


@maybe_skip_jdk_test
def test_simple_java_parser_analysis(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name='lockfile',
                    source="coursier_resolve.lockfile",
                )

                java_source(
                    name='simple-source',
                    source='SimpleSource.java',
                    dependencies=[':lockfile'],
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

    analysis = rule_runner.request(
        JavaSourceDependencyAnalysis,
        [source_files],
    )
    assert analysis.declared_package == "org.pantsbuild.example"
    assert analysis.imports == [
        JavaImport(name="java.util.Date"),
        JavaImport(name="bogus", is_asterisk=True),
        JavaImport(name="bogus.T", is_static=True),
        JavaImport(name="bogus.T.t"),
        JavaImport(name="bogus.Foo", is_asterisk=True, is_static=True),
    ]
    assert analysis.top_level_types == [
        "org.pantsbuild.example.SimpleSource",
        "org.pantsbuild.example.Foo",
    ]
    assert analysis.consumed_unqualified_types == [
        "some.other.Thing",
        "Date",
    ]


@maybe_skip_jdk_test
def test_java_parser_fallible_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name='lockfile',
                    source="coursier_resolve.lockfile",
                )

                java_source(
                    name='simple-source',
                    source='SimpleSource.java',
                    dependencies=[':lockfile'],
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
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name='lockfile',
                    source="coursier_resolve.lockfile",
                )

                java_source(
                    name='simple-source',
                    source='SimpleSource.java',
                    dependencies=[':lockfile'],
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
    assert analysis.declared_package == ""
    assert analysis.imports == []
    assert analysis.top_level_types == ["SimpleSource", "Foo"]
    assert analysis.consumed_unqualified_types == []


@maybe_skip_jdk_test
def test_java_parser_consumed_unqualified_types(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name='lockfile',
                    source="coursier_resolve.lockfile",
                )

                java_source(
                    name='source',
                    source='SomeUnqualifiedTypes.java',
                    dependencies=[':lockfile'],
                )
                """
            ),
            "SomeUnqualifiedTypes.java": dedent(
                """
                package org.pantsbuild.test;

                public class AnImpl implements SomeInterface {
                    public static class Inner extends SomeGeneric<String> {
                    }

                    Provided provided = provided;
                    public AnImpl(Provider<SomeThing> provider) {
                        this.provided = provider.provide();
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
    assert analysis.imports == []
    assert analysis.top_level_types == ["org.pantsbuild.test.AnImpl"]
    assert analysis.consumed_unqualified_types == [
        "SomeInterface",
        "SomeThing",
        "SomeGeneric",
        "String",
        "Provided",
        "Provider",
    ]
