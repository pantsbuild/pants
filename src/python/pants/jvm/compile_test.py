# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Tests of multi-language JVM compilation.

Tests of individual compilers should generally be written directly against the relevant `@rules`,
without any other language's `@rule`s present (to ensure that they work as expected in isolation).
But this module should include `@rules` for multiple languages, even though the module that it tests
(`compile.py`) only uses them indirectly via the `ClasspathEntryRequest` `@union`.
"""

from __future__ import annotations

import textwrap
from textwrap import dedent
from typing import Sequence, Type, cast

import chevron
import pytest

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
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.internals.native_engine import FileDigest
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
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import (
    CoursierFetchRequest,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.coursier_test_util import TestCoursierWrapper
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    maybe_skip_jdk_test,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict

DEFAULT_LOCKFILE = TestCoursierWrapper(
    CoursierResolvedLockfile(
        (
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.scala-lang", artifact="scala-library", version="2.13.6"
                ),
                file_name="org.scala-lang_scala-library_2.13.6.jar",
                direct_dependencies=Coordinates(),
                dependencies=Coordinates(),
                file_digest=FileDigest(
                    "f19ed732e150d3537794fd3fe42ee18470a3f707efd499ecd05a99e727ff6c8a", 5955737
                ),
            ),
        )
    )
).serialize(
    [
        ArtifactRequirement(
            coordinate=Coordinate(
                group="org.scala-lang", artifact="scala-library", version="2.13.6"
            )
        )
    ]
)

DEFAULT_SCALA_LIBRARY_TARGET = textwrap.dedent(
    """\
    jvm_artifact(
      name="org.scala-lang_scala-library_2.13.6",
      group="org.scala-lang",
      artifact="scala-library",
      version="2.13.6",
    )
    """
).replace("\n", " ")


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
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
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
def test_request_classification(rule_runner: RuleRunner) -> None:
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
                f"""\
                scala_sources(name='scala')
                java_sources(name='java')
                jvm_artifact(name='jvm_artifact', group='ex', artifact='ex', version='0.0.0')
                protobuf_source(name='proto', source="f.proto")
                protobuf_sources(name='protos')
                {DEFAULT_SCALA_LIBRARY_TARGET}
                """
            ),
            "f.proto": proto_source(),
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
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
def test_compile_mixed(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "scala_sources(name='main')",
            "3rdparty/jvm/BUILD": DEFAULT_SCALA_LIBRARY_TARGET,
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
            "Example.scala": scala_main_source(),
            "lib/BUILD": "java_sources()",
            "lib/C.java": java_lib_source(),
        }
    )
    rendered_classpath = rule_runner.request(
        RenderedClasspath, [Addresses([Address(spec_path="", target_name="main")])]
    )

    assert rendered_classpath.content[".Example.scala.main.scalac.jar"] == {
        "META-INF/MANIFEST.MF",
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
def test_compile_mixed_cycle(rule_runner: RuleRunner) -> None:
    # Add an extra import to the Java file which will force a cycle between them.
    rule_runner.write_files(
        {
            "BUILD": "scala_sources(name='main')",
            "3rdparty/jvm/BUILD": DEFAULT_SCALA_LIBRARY_TARGET,
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
            "Example.scala": scala_main_source(),
            "lib/BUILD": "java_sources()",
            "lib/C.java": java_lib_source(["org.pantsbuild.example.Main"]),
        }
    )

    main_address = Address(spec_path="", target_name="main")
    lib_address = Address(spec_path="lib")
    assert len(expect_single_expanded_coarsened_target(rule_runner, main_address).members) == 2
    rule_runner.request(Classpath, [Addresses([main_address, lib_address])])
