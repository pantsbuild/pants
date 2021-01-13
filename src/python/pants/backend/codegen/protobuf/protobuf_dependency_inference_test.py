# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Set

import pytest

from pants.backend.codegen.protobuf import protobuf_dependency_inference
from pants.backend.codegen.protobuf.protobuf_dependency_inference import (
    InferProtobufDependencies,
    ProtobufMapping,
    parse_proto_imports,
)
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary, ProtobufSources
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.mark.parametrize(
    "file_content,expected",
    [
        ("import 'foo.proto';", {"foo.proto"}),
        ("import'foo.proto';", {"foo.proto"}),
        ("import\t   'foo.proto'   \t;", {"foo.proto"}),
        ('import "foo.proto";', {"foo.proto"}),
        ("syntax = 'proto3';\nimport \"foo.proto\";", {"foo.proto"}),
        # We don't worry about matching opening and closing ' vs. " quotes; Protoc will error if
        # invalid.
        ("import 'foo.proto\";", {"foo.proto"}),
        ("import \"foo.proto';", {"foo.proto"}),
        # `public` modifier.
        ("import public 'foo.proto';", {"foo.proto"}),
        ("import\t  public'foo.proto';", {"foo.proto"}),
        ("importpublic 'foo.proto';", set()),
        # `weak` modifier.
        ("import weak 'foo.proto';", {"foo.proto"}),
        ("import\t  weak'foo.proto';", {"foo.proto"}),
        ("importweak 'foo.proto';", set()),
        # More complex file names.
        ("import 'path/to_dir/f.proto';", {"path/to_dir/f.proto"}),
        ("import 'path/to dir/f.proto';", {"path/to dir/f.proto"}),
        ("import 'path\\to-dir\\f.proto';", {"path\\to-dir\\f.proto"}),
        ("import 'âčĘï.proto';", {"âčĘï.proto"}),
        ("import '123.proto';", {"123.proto"}),
        # Invalid imports.
        ("import foo.proto;", set()),
        ("import 'foo.proto'", set()),
        ("import 'foo.protobuf';", set()),
        ("imprt 'foo.proto';", set()),
        # Multiple imports in a file.
        ("import 'foo.proto'; import \"bar.proto\";", {"foo.proto", "bar.proto"}),
        (
            dedent(
                """\
                syntax = "proto3";

                import 'dir/foo.proto';
                some random proto code;
                import public 'ábč.proto';
                """
            ),
            {"dir/foo.proto", "ábč.proto"},
        ),
    ],
)
def test_parse_proto_imports(file_content: str, expected: Set[str]) -> None:
    assert set(parse_proto_imports(file_content)) == expected


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *stripped_source_files.rules(),
            *protobuf_dependency_inference.rules(),
            QueryRule(ProtobufMapping, []),
            QueryRule(InferredDependencies, [InferProtobufDependencies]),
        ],
        target_types=[ProtobufLibrary],
    )


def test_protobuf_mapping(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--source-root-patterns=['root1', 'root2', 'root3']"])

    # Two proto files belonging to the same target. We should use two file addresses.
    rule_runner.create_files("root1/protos", ["f1.proto", "f2.proto"])
    rule_runner.add_to_build_file("root1/protos", "protobuf_library()")

    # These protos would result in the same stripped file name, so neither should be used.
    rule_runner.create_file("root1/two_owners/f.proto")
    rule_runner.add_to_build_file("root1/two_owners", "protobuf_library()")
    rule_runner.create_file("root2/two_owners/f.proto")
    rule_runner.add_to_build_file("root2/two_owners", "protobuf_library()")

    result = rule_runner.request(ProtobufMapping, [])
    assert result == ProtobufMapping(
        {
            "protos/f1.proto": Address("root1/protos", relative_file_path="f1.proto"),
            "protos/f2.proto": Address("root1/protos", relative_file_path="f2.proto"),
        }
    )


def test_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.create_file(
        "src/protos/project/f1.proto",
        dedent(
            """\
            import 'tests/f.proto';
            import 'unrelated_path/foo.proto";
            """
        ),
    )
    rule_runner.create_file("src/protos/project/f2.proto", "import 'project/f1.proto';")
    rule_runner.add_to_build_file("src/protos/project", "protobuf_library()")

    rule_runner.create_file("src/protos/tests/f.proto")
    rule_runner.add_to_build_file("src/protos/tests", "protobuf_library()")

    def run_dep_inference(address: Address) -> InferredDependencies:
        rule_runner.set_options(
            [
                "--backend-packages=pants.backend.codegen.protobuf.python",
                "--source-root-patterns=['src/protos']",
            ]
        )
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies, [InferProtobufDependencies(target[ProtobufSources])]
        )

    build_address = Address("src/protos/project")
    assert run_dep_inference(build_address) == InferredDependencies(
        [
            Address("src/protos/tests", relative_file_path="f.proto"),
            Address("src/protos/project", relative_file_path="f1.proto"),
        ],
        sibling_dependencies_inferrable=True,
    )

    file_address = Address("src/protos/project", relative_file_path="f1.proto")
    assert run_dep_inference(file_address) == InferredDependencies(
        [Address("src/protos/tests", relative_file_path="f.proto")],
        sibling_dependencies_inferrable=True,
    )
