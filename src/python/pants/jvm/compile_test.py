# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Tests of multi-language JVM compilation.

Tests of individual compilers should generally be written directly against the relevant `@rules`,
without any other language's `@rule`s present (to ensure that they work as expected in isolation).
But this module should include `@rules` for multiple languages, even though the module that it tests
(`compile.py`) only uses them indirectly via the `ClasspathEntryRequest` `@union`.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, cast
from unittest.mock import Mock

import chevron
import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.codegen.protobuf.java.rules import GenerateJavaFromProtobufRequest
from pants.backend.codegen.protobuf.java.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.scala.rules import rules as scala_protobuf_rules
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
from pants.core.util_rules.system_binaries import UnzipBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.process import Process, ProcessResult
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
    ClasspathEntry,
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
    make_resolve,
    maybe_skip_jdk_test,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import (
    PYTHON_BOOTSTRAP_ENV,
    QueryRule,
    RuleRunner,
    run_rule_with_mocks,
)
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


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
def antlr_jvm_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition("antlr.test.lock", ["org.antlr:antlr4:4.11.1"])


@pytest.fixture
def antlr_jvm_lockfile(
    antlr_jvm_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return antlr_jvm_lockfile_def.load(request)


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
            *scala_protobuf_rules(),
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
        preferred_impl: type[ClasspathEntryRequest] | None = None,
    ) -> tuple[type[ClasspathEntryRequest], type[ClasspathEntryRequest] | None]:
        impls_by_generator_source: dict[type[SourcesField], set[type[ClasspathEntryRequest]]] = (
            defaultdict(set)
        )
        for impl, fields in generators.items():
            for field in fields:
                impls_by_generator_source[field].add(impl)
        factory = ClasspathEntryRequestFactory(
            tuple(members),
            generators,
            FrozenDict(
                (field, frozenset(impls)) for field, impls in impls_by_generator_source.items()
            ),
        )

        req = factory.for_targets(
            CoarsenedTarget(targets, ()),
            CoursierResolveKey("example", "path", EMPTY_DIGEST),
            preferred_impl=preferred_impl,
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
            CompileJavaSourceRequest: frozenset([cast(type[SourcesField], ProtobufSourceField)]),
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

    # A codegen input consumed by more than one impl (e.g. protobuf, generated into both Java and
    # Scala) is ambiguous in the abstract...
    shared_generators = FrozenDict(
        {
            CompileJavaSourceRequest: frozenset([cast(type[SourcesField], ProtobufSourceField)]),
            CompileScalaSourceRequest: frozenset([cast(type[SourcesField], ProtobufSourceField)]),
        }
    )
    with pytest.raises(ClasspathSourceAmbiguity):
        classify([protos], all_members, shared_generators)
    with pytest.raises(ClasspathSourceAmbiguity):
        classify([proto], all_members, shared_generators)

    # ...but is resolved unambiguously once a `preferred_impl` is supplied, as happens when the
    # component is being resolved as the dependency of a concrete Java or Scala compile request
    # (see `classpath_dependency_requests`).
    assert (CompileJavaSourceRequest, None) == classify(
        [protos], all_members, shared_generators, preferred_impl=CompileJavaSourceRequest
    )
    assert (CompileScalaSourceRequest, None) == classify(
        [protos], all_members, shared_generators, preferred_impl=CompileScalaSourceRequest
    )
    assert (CompileJavaSourceRequest, None) == classify(
        [proto], all_members, shared_generators, preferred_impl=CompileJavaSourceRequest
    )
    assert (CompileScalaSourceRequest, None) == classify(
        [proto], all_members, shared_generators, preferred_impl=CompileScalaSourceRequest
    )


@pytest.fixture
def protobuf_multi_lang_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "protobuf-multi-lang.test.lock",
        [
            "com.google.protobuf:protobuf-java:4.33.2",
            "com.thesamet.scalapb:scalapb-runtime_2.13:0.11.6",
            "org.scala-lang:scala-library:2.13.6",
        ],
    )


@pytest.fixture
def protobuf_multi_lang_lockfile(
    protobuf_multi_lang_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return protobuf_multi_lang_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_protobuf_consumed_by_java_and_scala(
    rule_runner: RuleRunner, protobuf_multi_lang_lockfile: JVMLockfileFixture
) -> None:
    """A single, unparametrized `protobuf_sources` target can be depended on by both a
    `java_sources` and a `scala_sources` target without any disambiguating field, and each
    consumer resolves its own compiled classpath entry for it via the `preferred_impl` mechanism
    in `classpath_dependency_requests` -- rather than raising `ClasspathSourceAmbiguity`.
    """
    rule_runner.set_options(
        args=["--scala-version-for-resolve={'jvm-default': '2.13.6'}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": protobuf_multi_lang_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": protobuf_multi_lang_lockfile.requirements_as_jvm_artifact_targets(),
            "protos/BUILD": "protobuf_sources()",
            "protos/f.proto": proto_source(),
            "java/BUILD": "java_sources(dependencies=['//protos'])",
            "java/C.java": dedent(
                """\
                package org.pantsbuild.example.java;

                public class C {
                    public static String HELLO = "hello!";
                }
                """
            ),
            "scala/BUILD": "scala_sources(dependencies=['//protos'])",
            "scala/Main.scala": dedent(
                """\
                package org.pantsbuild.example.scala

                object Main {
                    def main(args: Array[String]): Unit = {
                        println("hello!")
                    }
                }
                """
            ),
        }
    )

    rendered_classpath = rule_runner.request(
        RenderedClasspath,
        [
            Addresses(
                [
                    Address("java", relative_file_path="C.java"),
                    Address("scala", relative_file_path="Main.scala"),
                ]
            )
        ],
    )

    # The Java root's dependency on `protos` was resolved via `CompileJavaSourceRequest`: the
    # generated sources are Java, compiled by javac.
    assert rendered_classpath.content["java.C.java.javac.jar"] == {
        "org/pantsbuild/example/java/C.class",
    }
    assert "protos.f.proto.javac.jar" in rendered_classpath.content

    # The Scala root's dependency on the *same* `protos` target was resolved via
    # `CompileScalaSourceRequest`: the generated sources are Scala, compiled by scalac -- proving
    # that the same, single, unparametrized `protobuf_sources` declaration serves both languages.
    assert rendered_classpath.content["scala.Main.scala.scalac.jar"] == {
        "org/pantsbuild/example/scala/Main$.class",
        "org/pantsbuild/example/scala/Main.class",
    }
    assert "protos.f.proto.scalac.jar" in rendered_classpath.content


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


def _jar(
    name: str,
    *,
    dependencies: Iterable[ClasspathEntry] = (),
    exports: Iterable[ClasspathEntry] = (),
) -> ClasspathEntry:
    return ClasspathEntry(
        Digest(hashlib.sha256(name.encode()).hexdigest(), len(name)),
        (f"{name}.jar",),
        dependencies=dependencies,
        exports=exports,
    )


def test_exports_follow_their_exporter_once() -> None:
    scala_library = _jar("scala-library")
    zio = _jar("zio", exports=[scala_library])
    zio_json = _jar("zio-json", exports=[scala_library])
    app = _jar("app", dependencies=[zio, zio_json])

    assert list(ClasspathEntry.closure([app])) == [app, zio, scala_library, zio_json]
    assert list(ClasspathEntry.args([zio, zio_json])) == [
        "zio.jar",
        "scala-library.jar",
        "zio-json.jar",
    ]
    assert list(ClasspathEntry.immutable_inputs_args([zio, zio_json], prefix="__cp")) == [
        f"__cp/{cpe.digest.fingerprint[:12]}/{cpe.filenames[0]}"
        for cpe in (zio, scala_library, zio_json)
    ]
    assert list(ClasspathEntry.immutable_inputs([zio, zio_json], prefix="__cp")) == [
        (f"__cp/{cpe.digest.fingerprint[:12]}", cpe.digest)
        for cpe in (zio, scala_library, zio_json)
    ]


def test_exports_are_transitive_and_their_dependencies_are_not_root() -> None:
    runtime_dep = _jar("runtime-dep")
    core = _jar("core", dependencies=[runtime_dep])
    api = _jar("api", exports=[core])
    bundle = _jar("bundle", exports=[api])
    user = _jar("user", dependencies=[bundle])

    assert list(ClasspathEntry.with_exports([bundle])) == [bundle, api, core]
    assert list(ClasspathEntry.closure([user])) == [user, bundle, api, core, runtime_dep]


def test_a_jar_that_is_both_an_artifact_and_an_export_is_listed_once() -> None:
    scala_library = _jar("scala-library")
    zio = _jar("zio", exports=[scala_library])
    zio_json = _jar("zio-json", exports=[_jar("zio"), scala_library])

    assert list(ClasspathEntry.args([zio, zio_json])) == [
        "zio.jar",
        "scala-library.jar",
        "zio-json.jar",
    ]
    assert list(ClasspathEntry.immutable_inputs_args([zio, zio_json])) == [
        f"{cpe.digest.fingerprint[:12]}/{cpe.filenames[0]}"
        for cpe in (zio, scala_library, zio_json)
    ]
    assert list(ClasspathEntry.immutable_inputs([zio, zio_json])) == [
        (cpe.digest.fingerprint[:12], cpe.digest) for cpe in (zio, scala_library, zio_json)
    ]


def test_transitive_covers_the_closure() -> None:
    scala_library = _jar("scala-library")
    zio = _jar("zio", exports=[scala_library])
    lib = _jar("lib", dependencies=[zio], exports=[_jar("lib-api")])
    app = _jar("app", dependencies=[lib, zio])
    closure = list(ClasspathEntry.closure([app]))

    assert list(ClasspathEntry.args([app], transitive=True)) == list(ClasspathEntry.args(closure))
    assert list(ClasspathEntry.immutable_inputs([app], prefix="__cp", transitive=True)) == list(
        ClasspathEntry.immutable_inputs(closure, prefix="__cp")
    )
    assert list(
        ClasspathEntry.immutable_inputs_args([app], prefix="__cp", transitive=True)
    ) == list(ClasspathEntry.immutable_inputs_args(closure, prefix="__cp"))
    assert list(ClasspathEntry.args([app])) == ["app.jar"]


def test_merge_keeps_exports() -> None:
    scala_library = _jar("scala-library")
    zio = _jar("zio", exports=[scala_library])
    app = _jar("app", dependencies=[zio])

    merged = ClasspathEntry.merge(EMPTY_DIGEST, [app, zio])

    assert merged.filenames == ("app.jar", "zio.jar")
    assert merged.dependencies == FrozenOrderedSet([zio])
    assert merged.exports == FrozenOrderedSet([scala_library])


def test_classpath_entry_equality() -> None:
    assert _jar("a") == _jar("a")
    assert _jar("a") != _jar("b")

    assert _jar("app", dependencies=[_jar("a")]) == _jar("app", dependencies=[_jar("a")])
    assert _jar("app", dependencies=[_jar("a")]) != _jar("app", dependencies=[_jar("b")])
    assert _jar("app", exports=[_jar("a")]) != _jar("app", dependencies=[_jar("a")])
    assert _jar("app", dependencies=[_jar("a"), _jar("b")]) != _jar(
        "app", dependencies=[_jar("b"), _jar("a")]
    )

    class Subclass(ClasspathEntry):
        pass

    assert Subclass(EMPTY_DIGEST) != ClasspathEntry(EMPTY_DIGEST)
    assert ClasspathEntry(EMPTY_DIGEST) != Subclass(EMPTY_DIGEST)
    assert _jar("app", dependencies=[Subclass(EMPTY_DIGEST)]) == _jar(
        "app", dependencies=[Subclass(EMPTY_DIGEST)]
    )
    assert _jar("app", dependencies=[ClasspathEntry(EMPTY_DIGEST)]) != _jar(
        "app", dependencies=[Subclass(EMPTY_DIGEST)]
    )

    @dataclass(frozen=True)
    class WithExtra(ClasspathEntry):
        extra: int

    def with_extra(extra: int) -> WithExtra:
        return WithExtra(EMPTY_DIGEST, (), FrozenOrderedSet(), FrozenOrderedSet(), extra)

    assert hash(with_extra(-1)) == hash(with_extra(-2))
    assert with_extra(-1) == with_extra(-1)
    assert with_extra(-1) != with_extra(-2)
    assert _jar("app", dependencies=[with_extra(-1)]) == _jar("app", dependencies=[with_extra(-1)])
    assert _jar("app", dependencies=[with_extra(-1)]) != _jar("app", dependencies=[with_extra(-2)])

    @dataclass(frozen=True, eq=False)
    class Validates(ClasspathEntry):
        extra: int

        def __post_init__(self) -> None:
            if self.extra < 0:
                raise ValueError(self.extra)

    def validates(extra: int) -> Validates:
        return Validates(EMPTY_DIGEST, (), FrozenOrderedSet(), FrozenOrderedSet(), extra)

    assert validates(1) in {validates(1)}
    assert _jar("app", dependencies=[validates(1)]) == _jar("app", dependencies=[validates(1)])

    class SameDigest(ClasspathEntry):
        def __eq__(self, other: Any) -> bool:
            return isinstance(other, SameDigest) and self.digest == other.digest

        def __hash__(self) -> int:
            return hash(self.digest)

    assert _jar("app", dependencies=[SameDigest(EMPTY_DIGEST, ["a.jar"])]) == _jar(
        "app", dependencies=[SameDigest(EMPTY_DIGEST, ["b.jar"])]
    )

    class EqualsBase(ClasspathEntry):
        def __eq__(self, other: Any) -> bool:
            if not isinstance(other, ClasspathEntry):
                return NotImplemented
            fields = ("digest", "filenames", "dependencies", "exports")
            return all(getattr(self, f) == getattr(other, f) for f in fields)

        __hash__ = ClasspathEntry.__hash__

    base_child, sub_child = _jar("a"), EqualsBase(_jar("a").digest, ["a.jar"])
    assert _jar("app", dependencies=[base_child]) == _jar("app", dependencies=[sub_child])
    assert _jar("app", dependencies=[sub_child]) == _jar("app", dependencies=[base_child])

    def nested():
        shared = _jar("shared")
        lib = _jar("lib", dependencies=[shared], exports=[shared])
        return _jar("app", dependencies=[lib, shared], exports=[lib])

    a, b = nested(), nested()
    assert a is not b
    assert a == b
    assert hash(a) == hash(b)


def test_classpath_entry_eq_is_linear_in_nodes_not_paths() -> None:
    def fan_out(width: int, depth: int, first_leaf: str = "leaf0") -> ClasspathEntry:
        level = tuple(_jar(first_leaf if i == 0 else f"leaf{i}") for i in range(width))
        for d in range(depth):
            level = tuple(
                _jar(f"n{d}_{i}", dependencies=level, exports=level[:1]) for i in range(width)
            )
        return _jar("root", dependencies=level)

    def all_nodes(root: ClasspathEntry) -> dict[int, ClasspathEntry]:
        nodes: dict[int, ClasspathEntry] = {}
        stack = [root]
        while stack:
            node = stack.pop()
            if id(node) not in nodes:
                nodes[id(node)] = node
                stack.extend(node.dependencies)
                stack.extend(node.exports)
        return nodes

    calls = 0
    original_helper = ClasspathEntry._eq_helper

    def counting(
        self: ClasspathEntry, other: ClasspathEntry, equal_items: set[tuple[int, int]]
    ) -> bool:
        nonlocal calls
        calls += 1
        return original_helper(self, other, equal_items)

    ClasspathEntry._eq_helper = counting  # type: ignore[method-assign]
    try:
        a, b = fan_out(6, 6), fan_out(6, 6)
        assert a == b
        nodes = all_nodes(a).values()
        nodes_and_edges = len(nodes) + sum(len(n.dependencies) + len(n.exports) for n in nodes)
        assert calls <= nodes_and_edges

        c = fan_out(6, 6, first_leaf="different")
        for node in [*all_nodes(a).values(), *all_nodes(c).values()]:
            object.__setattr__(node, "_hashcode", 0)
        assert a != c
    finally:
        ClasspathEntry._eq_helper = original_helper  # type: ignore[method-assign]


def test_loose_classfiles_extracts_each_jar_from_its_own_digest() -> None:
    scala_library = _jar("scala-library")
    zio = _jar("zio", exports=[scala_library])
    zio_json = _jar("zio-json", exports=[scala_library])
    lib = _jar("lib", exports=[zio, zio_json])
    extracted: list[tuple[Digest, str]] = []

    def extract(process: Process) -> ProcessResult:
        ((jar_dir, digest),) = process.immutable_input_digests.items()
        extracted.append((digest, os.path.relpath(process.argv[-1], jar_dir)))
        return Mock(output_digest=EMPTY_DIGEST)

    run_rule_with_mocks(
        classpath.loose_classfiles,
        rule_args=[lib, UnzipBinary("/usr/bin/unzip")],
        mock_calls={
            "pants.engine.process.fallible_to_exec_result_or_raise": extract,
            "pants.engine.intrinsics.merge_digests": lambda _: EMPTY_DIGEST,
            "pants.engine.intrinsics.remove_prefix": lambda _: EMPTY_DIGEST,
        },
    )

    assert extracted == [
        (cpe.digest, cpe.filenames[0]) for cpe in (lib, zio, scala_library, zio_json)
    ]


@maybe_skip_jdk_test
def test_jvm_artifact_exports_each_transitive_jar_as_its_own_entry(
    rule_runner: RuleRunner, antlr_jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/BUILD": antlr_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": antlr_jvm_lockfile.serialized_lockfile,
        }
    )
    classpath = rule_runner.request(
        Classpath,
        [Addresses([Address(spec_path="3rdparty/jvm", target_name="org.antlr_antlr4")])],
    )

    (antlr4,) = classpath.entries
    assert antlr4.filenames == ("org.antlr_antlr4_4.11.1.jar",)
    (antlr4_requirement,) = antlr_jvm_lockfile.requirements
    _, antlr4_dependencies = antlr_jvm_lockfile.lockfile.dependencies(
        make_resolve(rule_runner), antlr4_requirement.coordinate
    )
    assert [cpe.filenames for cpe in antlr4.exports] == [
        (dependency.file_name,) for dependency in antlr4_dependencies
    ]
    assert list(classpath.immutable_inputs_args(prefix="__cp")) == [
        f"__cp/{cpe.digest.fingerprint[:12]}/{cpe.filenames[0]}"
        for cpe in (antlr4, *antlr4.exports)
    ]


@maybe_skip_jdk_test
def test_javac_sees_jars_exported_by_a_direct_dependency(
    rule_runner: RuleRunner, antlr_jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/BUILD": antlr_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": antlr_jvm_lockfile.serialized_lockfile,
            "BUILD": "java_sources(name='lib', dependencies=['3rdparty/jvm:org.antlr_antlr4'])",
            "Token.java": dedent(
                """\
                package org.pantsbuild.example;

                import org.antlr.runtime.CommonToken;

                public class Token {
                    public static Object make() {
                        return new CommonToken(0);
                    }
                }
                """
            ),
        }
    )

    rendered_classpath = rule_runner.request(
        RenderedClasspath, [Addresses([Address(spec_path="", target_name="lib")])]
    )

    assert rendered_classpath.content[".Token.java.lib.javac.jar"] == {
        "org/pantsbuild/example/Token.class"
    }


@maybe_skip_jdk_test
def test_javac_exports_keep_each_exported_artifacts_jars_after_it(
    rule_runner: RuleRunner, antlr_jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/BUILD": antlr_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": antlr_jvm_lockfile.serialized_lockfile,
            "other/BUILD": "java_sources()",
            "other/Other.java": dedent(
                """\
                package org.pantsbuild.other;

                public class Other {}
                """
            ),
            "lib/BUILD": "java_sources(dependencies=['3rdparty/jvm:org.antlr_antlr4'])",
            "lib/Lib.java": dedent(
                """\
                package org.pantsbuild.lib;

                import org.antlr.runtime.CommonToken;
                import org.pantsbuild.other.Other;

                public class Lib {
                    public static CommonToken token() {
                        return new CommonToken(0);
                    }

                    public static Other other() {
                        return new Other();
                    }
                }
                """
            ),
            "app/BUILD": "java_sources()",
            "app/App.java": dedent(
                """\
                package org.pantsbuild.app;

                import org.pantsbuild.lib.Lib;

                public class App {
                    public static String describe() {
                        return Lib.token().getText() + Lib.other();
                    }
                }
                """
            ),
        }
    )

    lib_classpath = rule_runner.request(
        Classpath, [Addresses([Address("lib", relative_file_path="Lib.java")])]
    )
    lib_jar, antlr4_jar, *antlr4_exports, other_jar = lib_classpath.root_args()
    assert lib_jar.endswith(".javac.jar") and "Lib.java" in lib_jar
    assert antlr4_jar == "org.antlr_antlr4_4.11.1.jar"
    assert sorted(antlr4_exports) == [
        "com.ibm.icu_icu4j_71.1.jar",
        "org.abego.treelayout_org.abego.treelayout.core_1.0.3.jar",
        "org.antlr_ST4_4.3.4.jar",
        "org.antlr_antlr-runtime_3.5.3.jar",
        "org.antlr_antlr4-runtime_4.11.1.jar",
        "org.glassfish_javax.json_1.1.4.jar",
    ]
    assert other_jar.endswith(".javac.jar") and "Other.java" in other_jar

    rendered_classpath = rule_runner.request(
        RenderedClasspath, [Addresses([Address("app", relative_file_path="App.java")])]
    )
    assert {"org/pantsbuild/app/App.class"} in rendered_classpath.content.values()
