# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.codegen.protobuf.python import additional_fields, python_protobuf_module_mapper
from pants.backend.codegen.protobuf.python.python_protobuf_module_mapper import (
    PythonProtobufMappingRequest,
)
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.dependency_inference.module_mapper import (
    PythonFirstPartyModuleMappingPlugin,
)
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *additional_fields.rules(),
            *stripped_source_files.rules(),
            *python_protobuf_module_mapper.rules(),
            QueryRule(PythonFirstPartyModuleMappingPlugin, [PythonProtobufMappingRequest]),
        ],
        target_types=[ProtobufLibrary],
    )


def test_map_first_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--source-root-patterns=['root1', 'root2', 'root3']"])
    # Two proto files belonging to the same target. We should use two file addresses.
    rule_runner.create_files("root1/protos", ["f1.proto", "f2.proto"])
    rule_runner.add_to_build_file("root1/protos", "protobuf_library()")
    # These protos would result in the same module name, so neither should be used.
    rule_runner.create_file("root1/two_owners/f.proto")
    rule_runner.add_to_build_file("root1/two_owners", "protobuf_library()")
    rule_runner.create_file("root2/two_owners/f.proto")
    rule_runner.add_to_build_file("root2/two_owners", "protobuf_library()")
    # A file with grpc. This also uses the `python_source_root` mechanism, which should be
    # irrelevant to the module mapping because we strip source roots.
    rule_runner.create_file("root1/tests/f.proto")
    rule_runner.add_to_build_file(
        "root1/tests", "protobuf_library(grpc=True, python_source_root='root3')"
    )

    result = rule_runner.request(
        PythonFirstPartyModuleMappingPlugin, [PythonProtobufMappingRequest()]
    )
    assert result.mapping == FrozenDict(
        {
            "protos.f1_pb2": Address("root1/protos", relative_file_path="f1.proto"),
            "protos.f2_pb2": Address("root1/protos", relative_file_path="f2.proto"),
            "tests.f_pb2": Address("root1/tests", relative_file_path="f.proto"),
            "tests.f_pb2_grpc": Address("root1/tests", relative_file_path="f.proto"),
        }
    )
