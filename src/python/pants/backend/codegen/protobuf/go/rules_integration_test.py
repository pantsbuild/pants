# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.codegen.protobuf.go.rules import GenerateGoFromProtobufRequest
from pants.backend.codegen.protobuf.go.rules import rules as go_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_types_rules
from pants.backend.go.target_types import GoPackageTarget
from pants.backend.go.util_rules import sdk
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *jdk_rules(),
            *protobuf_target_types_rules(),
            *stripped_source_files.rules(),
            *go_protobuf_rules(),
            *sdk.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateGoFromProtobufRequest]),
            QueryRule(DigestContents, (Digest,)),
        ],
        target_types=[
            GoPackageTarget,
            ProtobufSourcesGeneratorTarget,
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
        [GenerateGoFromProtobufRequest(protocol_sources.snapshot, tgt)],
    )
    sources_contents = rule_runner.request(DigestContents, [generated_sources.snapshot.digest])
    for sc in sources_contents:
        print(f"{sc.path}:\n{sc.content.decode()}")
    assert set(generated_sources.snapshot.files) == set(expected_files)


def test_generates_go(rule_runner: RuleRunner) -> None:
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

                option go_package = "example.com/dir1";

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

                option go_package = "example.com/dir1";

                package dir1;
                """
            ),
            "src/protobuf/dir1/BUILD": "protobuf_sources()",
            "src/protobuf/dir2/f.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/dir2";

                package dir2;

                import "dir1/f.proto";
                """
            ),
            "src/protobuf/dir2/BUILD": ("protobuf_sources(dependencies=['src/protobuf/dir1'])"),
            # Test another source root.
            "tests/protobuf/test_protos/f.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/test_protos";

                package test_protos;

                import "dir2/f.proto";
                """
            ),
            "tests/protobuf/test_protos/BUILD": (
                "protobuf_sources(dependencies=['src/protobuf/dir2'])"
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
        ("src/protobuf/dir1/f.pb.go",),
    )
    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f2.proto"),
        ("src/protobuf/dir1/f2.pb.go",),
    )
    assert_gen(
        Address("src/protobuf/dir2", relative_file_path="f.proto"),
        ("src/protobuf/dir2/f.pb.go",),
    )
    assert_gen(
        Address("tests/protobuf/test_protos", relative_file_path="f.proto"),
        ("tests/protobuf/test_protos/f.pb.go",),
    )


def test_generates_go_grpc(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "protos/BUILD": "protobuf_sources(go_grpc=True)",
            "protos/service.proto": dedent(
                """\
            syntax = "proto3";

            option go_package = "example.com/protos";

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
        }
    )
    assert_files_generated(
        rule_runner,
        Address("protos", relative_file_path="service.proto"),
        source_roots=["/"],
        expected_files=[
            "protos/service.pb.go",
            "protos/service_grpc.pb.go",
        ],
    )
