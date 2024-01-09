# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf.python import additional_fields, python_protobuf_module_mapper
from pants.backend.codegen.protobuf.python.python_protobuf_module_mapper import (
    PythonProtobufMappingMarker,
)
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as python_protobuf_target_types_rules
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    ModuleProvider,
    ModuleProviderType,
)
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *additional_fields.rules(),
            *stripped_source_files.rules(),
            *python_protobuf_module_mapper.rules(),
            *python_protobuf_target_types_rules(),
            QueryRule(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


def test_map_first_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--source-root-patterns=['root1', 'root2', 'root3']",
            "--python-enable-resolves",
            "--python-resolves={'python-default': '', 'another-resolve': ''}",
        ]
    )
    rule_runner.write_files(
        {
            "root1/protos/f1.proto": "",
            "root1/protos/f2.proto": "",
            "root1/protos/BUILD": "protobuf_sources()",
            # These protos will result in the same module name.
            "root1/two_owners/f.proto": "",
            "root1/two_owners/BUILD": "protobuf_sources()",
            "root2/two_owners/f.proto": "",
            "root2/two_owners/BUILD": "protobuf_sources()",
            "root1/tests/f.proto": "",
            "root1/tests/BUILD": dedent(
                """\
                protobuf_sources(
                    grpc=True,
                    # This should be irrelevant to the module mapping because we strip source roots.
                    python_source_root='root3',
                    python_resolve='another-resolve',
                )
                """
            ),
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "protos.f1_pb2": providers(
                    [Address("root1/protos", relative_file_path="f1.proto")]
                ),
                "protos.f2_pb2": providers(
                    [Address("root1/protos", relative_file_path="f2.proto")]
                ),
                "two_owners.f_pb2": providers(
                    [
                        Address("root1/two_owners", relative_file_path="f.proto"),
                        Address("root2/two_owners", relative_file_path="f.proto"),
                    ]
                ),
            },
            "another-resolve": {
                "tests.f_pb2": providers([Address("root1/tests", relative_file_path="f.proto")]),
                "tests.f_pb2_grpc": providers(
                    [Address("root1/tests", relative_file_path="f.proto")]
                ),
            },
        }
    )


def test_top_level_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--source-root-patterns=['/']", "--python-enable-resolves"])
    rule_runner.write_files({"protos/f.proto": "", "protos/BUILD": "protobuf_sources()"})
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "protos.f_pb2": providers([Address("protos", relative_file_path="f.proto")])
            }
        }
    )


def test_map_grpclib_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--source-root-patterns=['/']",
            "--python-enable-resolves",
            "--python-protobuf-grpclib-plugin",
            "--no-python-protobuf-grpcio-plugin",
        ]
    )
    rule_runner.write_files({"protos/f.proto": "", "protos/BUILD": "protobuf_sources(grpc=True)"})
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "protos.f_pb2": providers([Address("protos", relative_file_path="f.proto")]),
                "protos.f_grpc": providers([Address("protos", relative_file_path="f.proto")]),
            }
        }
    )
