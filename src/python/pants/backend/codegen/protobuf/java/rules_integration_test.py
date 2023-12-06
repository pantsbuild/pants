# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.codegen.protobuf.java.rules import GenerateJavaFromProtobufRequest
from pants.backend.codegen.protobuf.java.rules import rules as java_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.backend.experimental.java.register import rules as java_backend_rules
from pants.backend.java.compile.javac import CompileJavaSourceRequest
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JavaSourceTarget
from pants.engine.addresses import Address, Addresses
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.jvm import testutil
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner

GRPC_PROTO_STANZA = """
syntax = "proto3";

package dir1;

// The greeter service definition.
service Greeter {
  // Sends a greeting
  rpc SayHello (HelloRequest) returns (HelloReply) {}
}

// The request message containing the user's name.
message HelloRequest {
  string name = 1;
}

// The response message containing the greetings
message HelloReply {
  string message = 1;
}
"""


@pytest.fixture
def protobuf_java_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "protobuf-java.test.lock",
        ["com.google.protobuf:protobuf-java:3.19.4"],
    )


@pytest.fixture
def protobuf_java_lockfile(
    protobuf_java_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return protobuf_java_lockfile_def.load(request)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *java_backend_rules(),
            *java_protobuf_rules(),
            *target_types_rules(),
            *testutil.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateJavaFromProtobufRequest]),
            QueryRule(RenderedClasspath, (CompileJavaSourceRequest,)),
            QueryRule(Addresses, (DependenciesRequest,)),
        ],
        target_types=[
            ProtobufSourcesGeneratorTarget,
            JavaSourceTarget,
            JavaSourcesGeneratorTarget,
            JvmArtifactTarget,
        ],
    )


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: list[str] | None = None,
) -> None:
    args = [f"--source-root-patterns={repr(source_roots)}", *(extra_args or ())]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GenerateJavaFromProtobufRequest(protocol_sources.snapshot, tgt)],
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


def test_generates_java(
    rule_runner: RuleRunner, protobuf_java_lockfile: JVMLockfileFixture
) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Protobuf files can import other protobuf files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    #  * Dependency inference between Java and Protobuf sources.
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(
                """\
                syntax = "proto3";
                option java_package = "org.pantsbuild.java.proto";

                package dir1;

                message Person {
                  string name = 1;
                  int32 id = 2;
                  string email = 3;
                }
                """
            ),
            "src/protobuf/dir1/f2.proto": dedent(
                """\
                syntax = "proto3";

                package dir1;
                """
            ),
            "src/protobuf/dir1/BUILD": "protobuf_sources()",
            "src/protobuf/dir2/f3.proto": dedent(
                """\
                syntax = "proto3";

                package dir2;

                import "dir1/f.proto";
                """
            ),
            "src/protobuf/dir2/BUILD": "protobuf_sources(dependencies=['src/protobuf/dir1'])",
            # Test another source root.
            "tests/protobuf/test_protos/f.proto": dedent(
                """\
                syntax = "proto3";

                package test_protos;

                import "dir2/f3.proto";
                """
            ),
            "tests/protobuf/test_protos/BUILD": (
                "protobuf_sources(dependencies=['src/protobuf/dir2'])"
            ),
            "3rdparty/jvm/default.lock": protobuf_java_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": protobuf_java_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/BUILD": "java_sources()",
            "src/jvm/TestJavaProtobuf.java": dedent(
                """\
                package org.pantsbuild.java.example;

                import org.pantsbuild.java.proto.F.Person;

                public class TestJavaProtobuf {
                  Person person;
                }
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: str) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["src/python", "/src/protobuf", "/tests/protobuf"],
            expected_files=[expected],
        )

    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        "src/protobuf/org/pantsbuild/java/proto/F.java",
    )
    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f2.proto"), "src/protobuf/dir1/F2.java"
    )
    assert_gen(
        Address("src/protobuf/dir2", relative_file_path="f3.proto"), "src/protobuf/dir2/F3.java"
    )
    assert_gen(
        Address("tests/protobuf/test_protos", relative_file_path="f.proto"),
        "tests/protobuf/test_protos/F.java",
    )

    tgt = rule_runner.get_target(Address("src/jvm", relative_file_path="TestJavaProtobuf.java"))
    dependencies = rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
    assert Address("src/protobuf/dir1", relative_file_path="f.proto") in dependencies

    request = CompileJavaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="src/jvm")
        ),
        resolve=make_resolve(rule_runner),
    )
    _ = rule_runner.request(RenderedClasspath, [request])


@pytest.fixture
def protobuf_java_grpc_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "protobuf-grpc-java.test.lock",
        [
            "com.google.protobuf:protobuf-java:3.19.4",
            "io.grpc:grpc-netty-shaded:1.48.0",
            "io.grpc:grpc-protobuf:1.48.0",
            "io.grpc:grpc-stub:1.48.0",
            "org.apache.tomcat:annotations-api:6.0.53",
        ],
    )


@pytest.fixture
def protobuf_java_grpc_lockfile(
    protobuf_java_grpc_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return protobuf_java_grpc_lockfile_def.load(request)


def test_generates_grpc_java(
    rule_runner: RuleRunner, protobuf_java_grpc_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "protos/BUILD": "protobuf_sources(grpc=True)",
            "protos/service.proto": dedent(
                """\
            syntax = "proto3";
            option java_package = "org.pantsbuild.java.proto";

            package service;

            message TestMessage {
              string foo = 1;
            }

            service TestService {
              rpc noStreaming (TestMessage) returns (TestMessage);
              rpc clientStreaming (stream TestMessage) returns (TestMessage);
              rpc serverStreaming (TestMessage) returns (stream TestMessage);
              rpc bothStreaming (stream TestMessage) returns (stream TestMessage);
            }
            """
            ),
            "3rdparty/jvm/default.lock": protobuf_java_grpc_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": protobuf_java_grpc_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/BUILD": "java_sources(dependencies=['protos'])",
            "src/jvm/TestJavaProtobufGrpc.java": dedent(
                """\
                package org.pantsbuild.java.example;
                import org.pantsbuild.java.proto.TestServiceGrpc;
                public class TestJavaProtobufGrpc {
                  TestServiceGrpc service;
                }
                """
            ),
        }
    )
    assert_files_generated(
        rule_runner,
        Address("protos", relative_file_path="service.proto"),
        source_roots=["/"],
        expected_files=[
            "org/pantsbuild/java/proto/Service.java",
            "org/pantsbuild/java/proto/TestServiceGrpc.java",
        ],
    )

    request = CompileJavaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="src/jvm")
        ),
        resolve=make_resolve(rule_runner),
    )
    _ = rule_runner.request(RenderedClasspath, [request])
