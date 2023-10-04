# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import PythonProtobufMypyPlugin
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    rules as protobuf_subsystem_rules,
)
from pants.backend.codegen.protobuf.python.rules import GeneratePythonFromProtobufRequest
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.backend.python.dependency_inference import module_mapper
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.source.source_root import NoSourceRootError
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error
from pants.util.resources import read_sibling_resource

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
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *protobuf_rules(),
            *protobuf_subsystem_rules(),
            *additional_fields.rules(),
            *stripped_source_files.rules(),
            *target_types_rules(),
            *module_mapper.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GeneratePythonFromProtobufRequest]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    mypy: bool = False,
    extra_args: list[str] | None = None,
) -> None:
    args = [
        f"--source-root-patterns={repr(source_roots)}",
        "--no-python-protobuf-infer-runtime-dependency",
        *(extra_args or ()),
    ]
    if mypy:
        args.append("--python-protobuf-mypy-plugin")
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GeneratePythonFromProtobufRequest(protocol_sources.snapshot, tgt)],
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


def test_generates_python(rule_runner: RuleRunner) -> None:
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
            "src/protobuf/dir2/BUILD": dedent(
                """\
                protobuf_sources(dependencies=['src/protobuf/dir1'],
                python_source_root='src/python')
                """
            ),
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
        Address("src/protobuf/dir1", relative_file_path="f.proto"), "src/protobuf/dir1/f_pb2.py"
    )
    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f2.proto"), "src/protobuf/dir1/f2_pb2.py"
    )
    assert_gen(
        Address("src/protobuf/dir2", relative_file_path="f.proto"), "src/python/dir2/f_pb2.py"
    )
    assert_gen(
        Address("tests/protobuf/test_protos", relative_file_path="f.proto"),
        "tests/protobuf/test_protos/f_pb2.py",
    )


def test_top_level_proto_root(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "protos/f.proto": dedent(
                """\
                syntax = "proto3";

                package protos;
                """
            ),
            "protos/BUILD": "protobuf_sources()",
        }
    )
    assert_files_generated(
        rule_runner,
        Address("protos", relative_file_path="f.proto"),
        source_roots=["/"],
        expected_files=["protos/f_pb2.py"],
    )


def test_top_level_python_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/proto/protos/f.proto": dedent(
                """\
                syntax = "proto3";

                package protos;
                """
            ),
            "src/proto/protos/BUILD": "protobuf_sources(python_source_root='.')",
        }
    )
    assert_files_generated(
        rule_runner,
        Address("src/proto/protos", relative_file_path="f.proto"),
        source_roots=["/", "src/proto"],
        expected_files=["protos/f_pb2.py"],
    )


def test_bad_python_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(
                """\
                syntax = "proto3";

                package dir1;
                """
            ),
            "src/protobuf/dir1/BUILD": "protobuf_sources(python_source_root='notasourceroot')",
        }
    )
    with engine_error(NoSourceRootError):
        assert_files_generated(
            rule_runner,
            Address("src/protobuf/dir1", relative_file_path="f.proto"),
            source_roots=["src/protobuf"],
            expected_files=[],
        )


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(PythonProtobufMypyPlugin.default_interpreter_constraints),
)
def test_mypy_plugin(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
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
            "src/protobuf/dir1/BUILD": "protobuf_sources()",
        }
    )
    assert_files_generated(
        rule_runner,
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        source_roots=["src/protobuf"],
        extra_args=[
            "--python-protobuf-mypy-plugin",
            f"--mypy-protobuf-interpreter-constraints=['=={major_minor_interpreter}.*']",
        ],
        expected_files=["src/protobuf/dir1/f_pb2.py", "src/protobuf/dir1/f_pb2.pyi"],
    )


def test_grpc(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(GRPC_PROTO_STANZA),
            "src/protobuf/dir1/BUILD": "protobuf_sources(grpc=True)",
        }
    )
    assert_files_generated(
        rule_runner,
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        source_roots=["src/protobuf"],
        expected_files=["src/protobuf/dir1/f_pb2.py", "src/protobuf/dir1/f_pb2_grpc.py"],
    )


def test_grpc_mypy_plugin(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(GRPC_PROTO_STANZA),
            "src/protobuf/dir1/BUILD": "protobuf_sources(grpc=True)",
        }
    )
    assert_files_generated(
        rule_runner,
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        source_roots=["src/protobuf"],
        mypy=True,
        expected_files=[
            "src/protobuf/dir1/f_pb2.py",
            "src/protobuf/dir1/f_pb2.pyi",
            "src/protobuf/dir1/f_pb2_grpc.py",
            "src/protobuf/dir1/f_pb2_grpc.pyi",
        ],
    )


def test_grpc_pre_v2_mypy_plugin(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(GRPC_PROTO_STANZA),
            "src/protobuf/dir1/BUILD": "protobuf_sources(grpc=True)",
            "mypy-protobuf.lock": read_sibling_resource(
                __name__, "test_grpc_pre_v2_mypy_plugin.lock"
            ),
        }
    )
    assert_files_generated(
        rule_runner,
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        source_roots=["src/protobuf"],
        extra_args=[
            "--python-protobuf-mypy-plugin",
            "--python-resolves={'mypy-protobuf':'mypy-protobuf.lock'}",
            "--mypy-protobuf-install-from-resolve=mypy-protobuf",
        ],
        expected_files=[
            "src/protobuf/dir1/f_pb2.py",
            "src/protobuf/dir1/f_pb2.pyi",
            "src/protobuf/dir1/f_pb2_grpc.py",
        ],
    )
