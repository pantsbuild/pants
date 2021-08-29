# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import PythonProtobufMypyPlugin
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    rules as protobuf_subsystem_rules,
)
from pants.backend.codegen.protobuf.python.rules import GeneratePythonFromProtobufRequest
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary, ProtobufSources
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.source.source_root import NoSourceRootError
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
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
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *protobuf_rules(),
            *protobuf_subsystem_rules(),
            *additional_fields.rules(),
            *stripped_source_files.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GeneratePythonFromProtobufRequest]),
        ],
        target_types=[ProtobufLibrary],
    )


def assert_files_generated(
    rule_runner: RuleRunner,
    spec: str,
    *,
    expected_files: List[str],
    source_roots: List[str],
    mypy: bool = False,
    extra_args: list[str] | None = None,
) -> None:
    options = [
        "--backend-packages=pants.backend.codegen.protobuf.python",
        f"--source-root-patterns={repr(source_roots)}",
        *(extra_args or ()),
    ]
    if mypy:
        options.append("--python-protobuf-mypy-plugin")
    rule_runner.set_options(
        options,
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    tgt = rule_runner.get_target(Address(spec))
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSources])]
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
            "src/protobuf/dir1/BUILD": "protobuf_library()",
            "src/protobuf/dir2/f.proto": dedent(
                """\
                syntax = "proto3";

                package dir2;

                import "dir1/f.proto";
                """
            ),
            "src/protobuf/dir2/BUILD": (
                "protobuf_library(dependencies=['src/protobuf/dir1'], "
                "python_source_root='src/python')"
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
                "protobuf_library(dependencies=['src/protobuf/dir2'])"
            ),
        }
    )
    source_roots = ["src/python", "/src/protobuf", "/tests/protobuf"]
    assert_files_generated(
        rule_runner,
        "src/protobuf/dir1",
        source_roots=source_roots,
        expected_files=["src/protobuf/dir1/f_pb2.py", "src/protobuf/dir1/f2_pb2.py"],
    )
    assert_files_generated(
        rule_runner,
        "src/protobuf/dir2",
        source_roots=source_roots,
        expected_files=["src/python/dir2/f_pb2.py"],
    )
    assert_files_generated(
        rule_runner,
        "tests/protobuf/test_protos",
        source_roots=source_roots,
        expected_files=["tests/protobuf/test_protos/f_pb2.py"],
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
            "protos/BUILD": "protobuf_library()",
        }
    )
    assert_files_generated(
        rule_runner, "protos", source_roots=["/"], expected_files=["protos/f_pb2.py"]
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
            "src/proto/protos/BUILD": "protobuf_library(python_source_root='.')",
        }
    )
    assert_files_generated(
        rule_runner,
        "src/proto/protos",
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
            "src/protobuf/dir1/BUILD": "protobuf_library(python_source_root='notasourceroot')",
        }
    )
    with pytest.raises(ExecutionError) as exc:
        assert_files_generated(
            rule_runner, "src/protobuf/dir1", source_roots=["src/protobuf"], expected_files=[]
        )
    assert len(exc.value.wrapped_exceptions) == 1
    assert isinstance(exc.value.wrapped_exceptions[0], NoSourceRootError)


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
            "src/protobuf/dir1/BUILD": "protobuf_library()",
        }
    )
    assert_files_generated(
        rule_runner,
        "src/protobuf/dir1",
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
            "src/protobuf/dir1/BUILD": "protobuf_library(grpc=True)",
        }
    )
    assert_files_generated(
        rule_runner,
        "src/protobuf/dir1",
        source_roots=["src/protobuf"],
        expected_files=["src/protobuf/dir1/f_pb2.py", "src/protobuf/dir1/f_pb2_grpc.py"],
    )


def test_grpc_mypy_plugin(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(GRPC_PROTO_STANZA),
            "src/protobuf/dir1/BUILD": "protobuf_library(grpc=True)",
        }
    )
    assert_files_generated(
        rule_runner,
        "src/protobuf/dir1",
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
            "src/protobuf/dir1/BUILD": "protobuf_library(grpc=True)",
        }
    )
    assert_files_generated(
        rule_runner,
        "src/protobuf/dir1",
        source_roots=["src/protobuf"],
        extra_args=[
            "--python-protobuf-mypy-plugin",
            "--mypy-protobuf-version=mypy-protobuf==1.24",
            "--mypy-protobuf-lockfile=<none>",
        ],
        expected_files=[
            "src/protobuf/dir1/f_pb2.py",
            "src/protobuf/dir1/f_pb2.pyi",
            "src/protobuf/dir1/f_pb2_grpc.py",
        ],
    )
