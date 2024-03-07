# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Tests of multi-language JVM compilation.

Tests of individual compilers should generally be written directly against the relevant `@rules`,
without any other language's `@rule`s present (to ensure that they work as expected in isolation).
But this module should include `@rules` for multiple languages, even though the module that it tests
(`compile.py`) only uses them indirectly via the `ClasspathEntryRequest` `@union`.
"""

from __future__ import annotations

from textwrap import dedent
from typing import Sequence, Type, cast

import chevron
import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.codegen.protobuf.java.rules import GenerateJavaFromProtobufRequest
from pants.backend.codegen.protobuf.java.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_types_rules
from pants.backend.java.compile.javac import CompileJavaSourceRequest
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import (
    JavaFieldSet,
    JavaGeneratorFieldSet,
    JavaSourcesGeneratorTarget,
)
from pants.backend.java.target_types import rules as java_target_types_rules
from pants.backend.scala.compile.scalac import CompileScalaSourceRequest
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.dependency_inference.rules import rules as scala_dep_inf_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.build_graph.address import Address
from pants.core.target_types import FilesGeneratorTarget, RelocatedFiles
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.target import (
    CoarsenedTarget,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Target,
    UnexpandedTargets,
)
from pants.jvm import classpath, jdk_rules, testutil
from pants.jvm.classpath import Classpath
from pants.jvm.compile import (
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    ClasspathSourceAmbiguity,
    ClasspathSourceMissing,
)
from pants.jvm.goals import lockfile
from pants.jvm.resolve.coursier_fetch import CoursierFetchRequest
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    maybe_skip_jdk_test,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def scala_stdlib_jvm_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "scala-library-2.13.test.lock",
        ["org.scala-lang:scala-library:2.13.8"],
    )


@pytest.fixture
def scala_stdlib_jvm_lockfile(
    scala_stdlib_jvm_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scala_stdlib_jvm_lockfile_def.load(request)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *lockfile.rules(),
            *classpath.rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *java_dep_inf_rules(),
            *scala_dep_inf_rules(),
            *strip_jar.rules(),
            *javac_rules(),
            *jdk_rules.rules(),
            *scalac_rules(),
            *source_files.rules(),
            *scala_target_types_rules(),
            *java_target_types_rules(),
            *util_rules(),
            *testutil.rules(),
            *protobuf_rules(),
            *stripped_source_files.rules(),
            *protobuf_target_types_rules(),
            QueryRule(Classpath, (Addresses,)),
            QueryRule(RenderedClasspath, (Addresses,)),
            QueryRule(UnexpandedTargets, (Addresses,)),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateJavaFromProtobufRequest]),
        ],
        target_types=[
            JavaSourcesGeneratorTarget,
            JvmArtifactTarget,
            ProtobufSourceTarget,
            ProtobufSourcesGeneratorTarget,
            ScalaSourcesGeneratorTarget,
            FilesGeneratorTarget,
            RelocatedFiles,
        ],
    )
    rule_runner.set_options(
        args=["--scala-version-for-resolve={'jvm-default': '2.13.8'}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


def java_lib_source(extra_imports: Sequence[str] = ()) -> str:
    return cast(
        str,
        chevron.render(
            dedent(
                """\
            package org.pantsbuild.example.lib;

            {{#extra_imports}}
            import {{.}};
            {{/extra_imports}}

            public class C {
                public static String HELLO = "hello!";
            }
            """
            ),
            {"extra_imports": extra_imports},
        ),
    )


def scala_main_source(extra_imports: Sequence[str] = ()) -> str:
    return cast(
        str,
        chevron.render(
            dedent(
                """\
            package org.pantsbuild.example

            import org.pantsbuild.example.lib.C
            {{#extra_imports}}
            import {{.}}
            {{/extra_imports}}

            object Main {
                def main(args: Array[String]): Unit = {
                    println(C.HELLO)
                }
            }
            """
            ),
            {"extra_imports": extra_imports},
        ),
    )


def proto_source() -> str:
    return dedent(
        """\
                syntax = "proto3";

                package dir1;

                message Person {
                  string name = 1;
                  int32 id = 2;
                  string email = 3;
                }
                """
    )


class CompileMockSourceRequest(ClasspathEntryRequest):
    field_sets = (JavaFieldSet, JavaGeneratorFieldSet)


@maybe_skip_jdk_test
def test_request_classification(
    rule_runner: RuleRunner, scala_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
    def classify(
        targets: Sequence[Target],
        members: Sequence[type[ClasspathEntryRequest]],
        generators: FrozenDict[type[ClasspathEntryRequest], frozenset[type[SourcesField]]],
    ) -> tuple[type[ClasspathEntryRequest], type[ClasspathEntryRequest] | None]:
        factory = ClasspathEntryRequestFactory(tuple(members), generators)

        req = factory.for_targets(
            CoarsenedTarget(targets, ()),
            CoursierResolveKey("example", "path", EMPTY_DIGEST),
        )
        return (type(req), type(req.prerequisite) if req.prerequisite else None)

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(name='scala')
                java_sources(name='java')
                jvm_artifact(name='jvm_artifact', group='ex', artifact='ex', version='0.0.0')
                protobuf_source(name='proto', source="f.proto")
                protobuf_sources(name='protos')
                """
            ),
            "f.proto": proto_source(),
            "3rdparty/jvm/BUILD": scala_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": scala_stdlib_jvm_lockfile.serialized_lockfile,
        }
    )
    scala, java, jvm_artifact, proto, protos = rule_runner.request(
        UnexpandedTargets,
        [
            Addresses(
                [
                    Address("", target_name="scala"),
                    Address("", target_name="java"),
                    Address("", target_name="jvm_artifact"),
                    Address("", target_name="proto"),
                    Address("", target_name="protos"),
                ]
            )
        ],
    )
    all_members = [CompileJavaSourceRequest, CompileScalaSourceRequest, CoursierFetchRequest]
    generators = FrozenDict(
        {
            CompileJavaSourceRequest: frozenset([cast(Type[SourcesField], ProtobufSourceField)]),
            CompileScalaSourceRequest: frozenset(),
        }
    )

    # Fully compatible.
    assert (CompileJavaSourceRequest, None) == classify([java], all_members, generators)
    assert (CompileScalaSourceRequest, None) == classify([scala], all_members, generators)
    assert (CoursierFetchRequest, None) == classify([jvm_artifact], all_members, generators)
    assert (CompileJavaSourceRequest, None) == classify([proto], all_members, generators)
    assert (CompileJavaSourceRequest, None) == classify([protos], all_members, generators)

    # Partially compatible.
    assert (CompileJavaSourceRequest, CompileScalaSourceRequest) == classify(
        [java, scala], all_members, generators
    )
    with pytest.raises(ClasspathSourceMissing):
        classify([java, jvm_artifact], all_members, generators)

    # None compatible.
    with pytest.raises(ClasspathSourceMissing):
        classify([java], [], generators)
    with pytest.raises(ClasspathSourceMissing):
        classify([scala, java, jvm_artifact], all_members, generators)

    # Too many compatible.
    with pytest.raises(ClasspathSourceAmbiguity):
        classify([java], [CompileJavaSourceRequest, CompileMockSourceRequest], generators)


@maybe_skip_jdk_test
def test_compile_mixed(
    rule_runner: RuleRunner, scala_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "BUILD": "scala_sources(name='main')",
            "3rdparty/jvm/BUILD": scala_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": scala_stdlib_jvm_lockfile.serialized_lockfile,
            "Example.scala": scala_main_source(),
            "lib/BUILD": "java_sources()",
            "lib/C.java": java_lib_source(),
        }
    )
    rendered_classpath = rule_runner.request(
        RenderedClasspath, [Addresses([Address(spec_path="", target_name="main")])]
    )

    assert rendered_classpath.content[".Example.scala.main.scalac.jar"] == {
        "org/pantsbuild/example/Main$.class",
        "org/pantsbuild/example/Main.class",
    }
    assert rendered_classpath.content["lib.C.java.javac.jar"] == {
        "org/pantsbuild/example/lib/C.class",
    }
    assert any(
        key.startswith("org.scala-lang_scala-library_") for key in rendered_classpath.content.keys()
    )
    assert len(rendered_classpath.content.keys()) == 3


@maybe_skip_jdk_test
def test_compile_mixed_cycle(
    rule_runner: RuleRunner, scala_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
    # Add an extra import to the Java file which will force a cycle between them.
    rule_runner.write_files(
        {
            "BUILD": "scala_sources(name='main')",
            "3rdparty/jvm/BUILD": scala_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": scala_stdlib_jvm_lockfile.serialized_lockfile,
            "Example.scala": scala_main_source(),
            "lib/BUILD": "java_sources()",
            "lib/C.java": java_lib_source(["org.pantsbuild.example.Main"]),
        }
    )

    main_address = Address(spec_path="", target_name="main")
    lib_address = Address(spec_path="lib")
    assert len(expect_single_expanded_coarsened_target(rule_runner, main_address).members) == 2
    rule_runner.request(Classpath, [Addresses([main_address, lib_address])])


@maybe_skip_jdk_test
def test_allow_files_dependency(
    rule_runner: RuleRunner, scala_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(name='main', dependencies=[":files", ":relocated"])
                files(name="files", sources=["File.txt"])
                relocated_files(
                    name="relocated",
                    files_targets=[":files"],
                    src="",
                    dest="files",
                )
                """
            ),
            "3rdparty/jvm/BUILD": scala_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": scala_stdlib_jvm_lockfile.serialized_lockfile,
            "Example.scala": dedent(
                """\
                package org.pantsbuild.example

                object Main {
                    def main(args: Array[String]): Unit = {
                        println("Hello World")
                    }
                }
                """
            ),
            "File.txt": "HELLO WORLD",
        }
    )

    main_address = Address(spec_path="", target_name="main")
    rule_runner.request(Classpath, [Addresses([main_address])])
