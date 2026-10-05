# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf import protobuf_dependency_inference
from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    rules as protobuf_subsystem_rules,
)
from pants.backend.codegen.protobuf.python.register import rules as python_protobuf_backend_rules
from pants.backend.codegen.protobuf.python.rules import GeneratePythonFromProtobufRequest
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_types_rules
from pants.backend.python import target_types_rules as python_target_types_rules
from pants.backend.python.dependency_inference import module_mapper
from pants.core.target_types import rules as core_target_types_rules
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.testutil.rule_runner import QueryRule, RuleRunner

# A minimal `buf.gen.yaml` template that invokes the python plugin built into protoc.
# `buf` shells out to `protoc` for `protoc_builtin` plugins, so `protoc` must be on PATH.
BUF_GEN_YAML = dedent(
    """\
    version: v2
    plugins:
      - protoc_builtin: python
        out: src/proto
    """
)

BUF_YAML = dedent(
    """\
    version: v2
    modules:
      - path: idl/proto
    """
)

SIMPLE_PROTO = dedent(
    """\
    syntax = "proto3";
    package foo;
    message Person {
      string name = 1;
      int32 id = 2;
    }
    """
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *protobuf_rules(),
            *python_protobuf_backend_rules(),
            *protobuf_dependency_inference.rules(),
            *protobuf_subsystem_rules(),
            *additional_fields.rules(),
            *protobuf_target_types_rules(),
            *python_target_types_rules.rules(),
            *stripped_source_files.rules(),
            *module_mapper.rules(),
            *core_target_types_rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GeneratePythonFromProtobufRequest]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


def _assert_generates(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: set[str],
    source_roots: list[str],
) -> None:
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_roots)}",
            "--no-python-protobuf-infer-runtime-dependency",
        ],
        env_inherit={"PATH"},
    )
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    generated = rule_runner.request(
        GeneratedSources,
        [GeneratePythonFromProtobufRequest(protocol_sources.snapshot, tgt)],
    )
    assert set(generated.snapshot.files) == expected_files


@pytest.mark.platform_specific_behavior
def test_buf_generates_python_at_out_directory(rule_runner: RuleRunner) -> None:
    """`out: src/proto` in `buf.gen.yaml` lands generated files at `src/proto/...`."""
    rule_runner.write_files(
        {
            "buf.yaml": BUF_YAML,
            "buf.gen.yaml": BUF_GEN_YAML,
            "idl/proto/foo/person.proto": SIMPLE_PROTO,
            "idl/proto/foo/BUILD": ("protobuf_sources(protobuf_generator='buf')"),
        }
    )
    _assert_generates(
        rule_runner,
        Address("idl/proto/foo", relative_file_path="person.proto"),
        expected_files={"src/proto/foo/person_pb2.py"},
        source_roots=["idl/proto", "src/proto"],
    )


@pytest.mark.platform_specific_behavior
def test_default_protoc_path_still_works(rule_runner: RuleRunner) -> None:
    """Regression: `protobuf_generator` unset (default `protoc`) is unchanged."""
    rule_runner.write_files(
        {
            "src/protobuf/foo/person.proto": SIMPLE_PROTO,
            "src/protobuf/foo/BUILD": "protobuf_sources()",
        }
    )
    _assert_generates(
        rule_runner,
        Address("src/protobuf/foo", relative_file_path="person.proto"),
        expected_files={"src/protobuf/foo/person_pb2.py"},
        source_roots=["src/protobuf"],
    )
