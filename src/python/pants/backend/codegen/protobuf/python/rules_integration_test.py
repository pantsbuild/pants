# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List

import pytest

from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.python.rules import GeneratePythonFromProtobufRequest
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary, ProtobufSources
from pants.backend.python.util_rules import extract_pex, pex
from pants.core.util_rules import external_tool, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.source.source_root import NoSourceRootError
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *protobuf_rules(),
            *extract_pex.rules(),
            *pex.rules(),
            *external_tool.rules(),
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
) -> None:
    options = [
        "--backend-packages=pants.backend.codegen.protobuf.python",
        f"--source-root-patterns={repr(source_roots)}",
    ]
    if mypy:
        options.append("--python-protobuf-mypy-plugin")
    rule_runner.set_options(options)
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

    rule_runner.create_file(
        "src/protobuf/dir1/f.proto",
        dedent(
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
    )
    rule_runner.create_file(
        "src/protobuf/dir1/f2.proto",
        dedent(
            """\
            syntax = "proto3";

            package dir1;
            """
        ),
    )
    rule_runner.add_to_build_file("src/protobuf/dir1", "protobuf_library()")

    rule_runner.create_file(
        "src/protobuf/dir2/f.proto",
        dedent(
            """\
            syntax = "proto3";

            package dir2;

            import "dir1/f.proto";
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/protobuf/dir2",
        "protobuf_library(dependencies=['src/protobuf/dir1'], python_source_root='src/python')",
    )

    # Test another source root.
    rule_runner.create_file(
        "tests/protobuf/test_protos/f.proto",
        dedent(
            """\
            syntax = "proto3";

            package test_protos;

            import "dir2/f.proto";
            """
        ),
    )
    rule_runner.add_to_build_file(
        "tests/protobuf/test_protos", "protobuf_library(dependencies=['src/protobuf/dir2'])"
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
    rule_runner.create_file(
        "protos/f.proto",
        dedent(
            """\
            syntax = "proto3";

            package protos;
            """
        ),
    )
    rule_runner.add_to_build_file("protos", "protobuf_library()")
    assert_files_generated(
        rule_runner, "protos", source_roots=["/"], expected_files=["protos/f_pb2.py"]
    )


def test_top_level_python_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.create_file(
        "src/proto/protos/f.proto",
        dedent(
            """\
            syntax = "proto3";

            package protos;
            """
        ),
    )
    rule_runner.add_to_build_file("src/proto/protos", "protobuf_library(python_source_root='.')")
    assert_files_generated(
        rule_runner,
        "src/proto/protos",
        source_roots=["/", "src/proto"],
        expected_files=["protos/f_pb2.py"],
    )


def test_bad_python_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.create_file(
        "src/protobuf/dir1/f.proto",
        dedent(
            """\
            syntax = "proto3";

            package dir1;
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/protobuf/dir1", "protobuf_library(python_source_root='notasourceroot')"
    )
    with pytest.raises(ExecutionError) as exc:
        assert_files_generated(
            rule_runner, "src/protobuf/dir1", source_roots=["src/protobuf"], expected_files=[]
        )
    assert len(exc.value.wrapped_exceptions) == 1
    assert isinstance(exc.value.wrapped_exceptions[0], NoSourceRootError)


def test_mypy_plugin(rule_runner: RuleRunner) -> None:
    rule_runner.create_file(
        "src/protobuf/dir1/f.proto",
        dedent(
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
    )
    rule_runner.add_to_build_file("src/protobuf/dir1", "protobuf_library()")
    assert_files_generated(
        rule_runner,
        "src/protobuf/dir1",
        source_roots=["src/protobuf"],
        mypy=True,
        expected_files=["src/protobuf/dir1/f_pb2.py", "src/protobuf/dir1/f_pb2.pyi"],
    )
