# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.codegen.protobuf.python import additional_fields, python_protobuf_module_mapper
from pants.backend.codegen.protobuf.python.python_protobuf_module_mapper import (
    PythonProtobufMappingMarker,
)
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.dependency_inference.module_mapper import FirstPartyPythonMappingImpl
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
            QueryRule(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker]),
        ],
        target_types=[ProtobufLibrary],
    )


def test_map_first_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--source-root-patterns=['root1', 'root2', 'root3']"])
    rule_runner.write_files(
        {
            "root1/protos/f1.proto": "",
            "root1/protos/f2.proto": "",
            "root1/protos/BUILD": "protobuf_library()",
            # These protos would result in the same module name, so neither should be used.
            "root1/two_owners/f.proto": "",
            "root1/two_owners/BUILD": "protobuf_library()",
            "root2/two_owners/f.proto": "",
            "root2/two_owners/BUILD": "protobuf_library()",
            # A file with grpc. This also uses the `python_source_root` mechanism, which should be
            # irrelevant to the module mapping because we strip source roots.
            "root1/tests/f.proto": "",
            "root1/tests/BUILD": "protobuf_library(grpc=True, python_source_root='root3')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])
    assert result == FirstPartyPythonMappingImpl(
        mapping=FrozenDict(
            {
                "protos.f1_pb2": (Address("root1/protos", relative_file_path="f1.proto"),),
                "protos.f2_pb2": (Address("root1/protos", relative_file_path="f2.proto"),),
                "tests.f_pb2": (Address("root1/tests", relative_file_path="f.proto"),),
                "tests.f_pb2_grpc": (Address("root1/tests", relative_file_path="f.proto"),),
            }
        ),
        ambiguous_modules=FrozenDict(
            {
                "two_owners.f_pb2": (
                    Address("root1/two_owners", relative_file_path="f.proto"),
                    Address("root2/two_owners", relative_file_path="f.proto"),
                )
            }
        ),
    )
