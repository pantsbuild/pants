# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf.java.rules import GenerateJavaFromProtobufRequest
from pants.backend.codegen.protobuf.java.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.internals.native_engine import FileDigest
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry
from pants.jvm.resolve.coursier_test_util import TestCoursierWrapper
from pants.jvm.target_types import JvmArtifactTarget
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

PROTOBUF_JAVA_RESOLVE = TestCoursierWrapper.new(
    entries=(
        CoursierLockfileEntry(
            coord=Coordinate(
                group="com.google.protobuf",
                artifact="protobuf-java",
                version="3.19.4",
            ),
            file_name="com.google.protobuf_protobuf-java_3.19.4.jar",
            direct_dependencies=Coordinates([]),
            dependencies=Coordinates([]),
            file_digest=FileDigest(
                "e8f524c2ad5965aae31b0527bf9d4e3bc19b0dfba8c05aef114fccc7f057c94d",
                1681869,
            ),
        ),
    ),
).serialize(
    [
        ArtifactRequirement(
            Coordinate(
                group="com.google.protobuf",
                artifact="protobuf-java",
                version="3.19.4",
            )
        )
    ]
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *protobuf_rules(),
            *artifact_mapper.rules(),
            *stripped_source_files.rules(),
            *target_types_rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateJavaFromProtobufRequest]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget, JvmArtifactTarget],
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


def test_generates_java(rule_runner: RuleRunner) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Protobuf files can import other protobuf files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(
                """\
                syntax = "proto3";

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
            "src/protobuf/dir2/f.proto": dedent(
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

                import "dir2/f.proto";
                """
            ),
            "tests/protobuf/test_protos/BUILD": (
                "protobuf_sources(dependencies=['src/protobuf/dir2'])"
            ),
            "3rdparty/jvm/default.lock": PROTOBUF_JAVA_RESOLVE,
            "3rdparty/BUILD": dedent(
                """\
                    jvm_artifact(
                        name="com.google.protobuf_protobuf-java_3.19.4",
                        group="com.google.protobuf",
                        artifact="protobuf-java",
                        version="3.19.4",
                        resolve="jvm-default",
                    )
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
        Address("src/protobuf/dir1", relative_file_path="f.proto"), "src/protobuf/dir1/F.java"
    )
    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f2.proto"), "src/protobuf/dir1/F2.java"
    )
    assert_gen(
        Address("src/protobuf/dir2", relative_file_path="f.proto"), "src/protobuf/dir2/F.java"
    )
    assert_gen(
        Address("tests/protobuf/test_protos", relative_file_path="f.proto"),
        "tests/protobuf/test_protos/F.java",
    )
