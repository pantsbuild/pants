# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.codegen.protobuf.scala.rules import GenerateScalaFromProtobufRequest
from pants.backend.codegen.protobuf.scala.rules import rules as scala_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_types_rules
from pants.backend.scala import target_types
from pants.backend.scala.compile.scalac import CompileScalaSourceRequest
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.dependency_inference.rules import rules as scala_dep_inf_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, distdir, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import QueryRule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.jvm import classpath, testutil
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
    maybe_skip_jdk_test,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner

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
def scalapb_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "scalapb.test.lock",
        [
            "com.thesamet.scalapb:scalapb-runtime_2.13:0.11.6",
            "org.scala-lang:scala-library:2.13.6",
        ],
    )


@pytest.fixture
def scalapb_lockfile(
    scalapb_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scalapb_lockfile_def.load(request)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *strip_jar.rules(),
            *scalac_rules(),
            *scala_dep_inf_rules(),
            *util_rules(),
            *jdk_rules(),
            *target_types.rules(),
            *protobuf_target_types_rules(),
            *stripped_source_files.rules(),
            *scala_protobuf_rules(),
            *artifact_mapper.rules(),
            *distdir.rules(),
            *testutil.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateScalaFromProtobufRequest]),
            QueryRule(DigestContents, (Digest,)),
            QueryRule(RenderedClasspath, (CompileScalaSourceRequest,)),
            QueryRule(Addresses, (DependenciesRequest,)),
        ],
        target_types=[
            ScalaSourceTarget,
            ScalaSourcesGeneratorTarget,
            ProtobufSourcesGeneratorTarget,
            JvmArtifactTarget,
        ],
    )
    rule_runner.set_options(
        [],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: Iterable[str] = (),
) -> None:
    args = [f"--source-root-patterns={repr(source_roots)}", *extra_args]
    rule_runner.set_options(args, env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GenerateScalaFromProtobufRequest(protocol_sources.snapshot, tgt)],
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


@maybe_skip_jdk_test
def test_generates_scala(rule_runner: RuleRunner, scalapb_lockfile: JVMLockfileFixture) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Protobuf files can import other protobuf files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    #  * Dependency inference between Scala and Protobuf sources.
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(
                """\
                syntax = "proto3";
                option java_package = "org.pantsbuild.scala.proto";

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
                option java_package = "org.pantsbuild.scala.proto";

                package dir1;
                """
            ),
            "src/protobuf/dir1/BUILD": "protobuf_sources()",
            "src/protobuf/dir2/f3.proto": dedent(
                """\
                syntax = "proto3";
                option java_package = "org.pantsbuild.scala.proto";

                package dir2;

                import "dir1/f.proto";
                """
            ),
            "src/protobuf/dir2/BUILD": ("protobuf_sources(dependencies=['src/protobuf/dir1'])"),
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
            "3rdparty/jvm/default.lock": scalapb_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scalapb_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/BUILD": "scala_sources()",
            "src/jvm/ScalaPBExample.scala": dedent(
                """\
                package org.pantsbuild.scala.example

                import org.pantsbuild.scala.proto.f.Person

                trait TestScrooge {
                  val person: Person
                }
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["src/python", "/src/protobuf", "/tests/protobuf"],
            expected_files=list(expected),
        )

    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        (
            "src/protobuf/org/pantsbuild/scala/proto/f/FProto.scala",
            "src/protobuf/org/pantsbuild/scala/proto/f/Person.scala",
        ),
    )
    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f2.proto"),
        ["src/protobuf/org/pantsbuild/scala/proto/f2/F2Proto.scala"],
    )
    assert_gen(
        Address("src/protobuf/dir2", relative_file_path="f3.proto"),
        ["src/protobuf/org/pantsbuild/scala/proto/f3/F3Proto.scala"],
    )
    assert_gen(
        Address("tests/protobuf/test_protos", relative_file_path="f.proto"),
        ["tests/protobuf/test_protos/f/FProto.scala"],
    )

    tgt = rule_runner.get_target(Address("src/jvm", relative_file_path="ScalaPBExample.scala"))
    dependencies = rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
    assert Address("src/protobuf/dir1", relative_file_path="f.proto") in dependencies

    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="src/jvm")
    )
    _ = rule_runner.request(
        RenderedClasspath,
        [CompileScalaSourceRequest(component=coarsened_target, resolve=make_resolve(rule_runner))],
    )


@maybe_skip_jdk_test
def test_top_level_proto_root(
    rule_runner: RuleRunner, scalapb_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "protos/f.proto": dedent(
                """\
                syntax = "proto3";

                package protos;
                """
            ),
            "protos/BUILD": "protobuf_sources()",
            "3rdparty/jvm/default.lock": scalapb_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scalapb_lockfile.requirements_as_jvm_artifact_targets(),
        }
    )
    assert_files_generated(
        rule_runner,
        Address("protos", relative_file_path="f.proto"),
        source_roots=["/"],
        expected_files=["protos/f/FProto.scala"],
    )


def test_generates_fs2_grpc_via_jvm_plugin(
    rule_runner: RuleRunner, scalapb_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "protos/BUILD": "protobuf_sources()",
            "protos/service.proto": dedent(
                """\
            syntax = "proto3";

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
            "3rdparty/jvm/default.lock": scalapb_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scalapb_lockfile.requirements_as_jvm_artifact_targets(),
        }
    )
    assert_files_generated(
        rule_runner,
        Address("protos", relative_file_path="service.proto"),
        source_roots=["/"],
        expected_files=[
            "service/service/ServiceProto.scala",
            "service/service/TestMessage.scala",
            "service/service/TestServiceFs2Grpc.scala",
        ],
        extra_args=["--scalapb-jvm-plugins=+['fs2=org.typelevel:fs2-grpc-codegen_2.12:2.3.1']"],
    )
