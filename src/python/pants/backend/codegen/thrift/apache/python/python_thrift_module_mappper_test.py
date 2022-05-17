# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.thrift.apache.python import (
    additional_fields,
    python_thrift_module_mapper,
)
from pants.backend.codegen.thrift.apache.python.python_thrift_module_mapper import (
    PythonThriftMappingMarker,
)
from pants.backend.codegen.thrift.target_types import ThriftSourcesGeneratorTarget
from pants.backend.codegen.thrift.target_types import rules as thrift_target_types_rules
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    ModuleProvider,
    ModuleProviderType,
)
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *additional_fields.rules(),
            *python_thrift_module_mapper.rules(),
            *thrift_target_types_rules(),
            QueryRule(FirstPartyPythonMappingImpl, [PythonThriftMappingMarker]),
        ],
        target_types=[ThriftSourcesGeneratorTarget],
    )


def test_map_first_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--source-root-patterns=['root1', 'root2']",
            "--python-enable-resolves",
            "--python-resolves={'python-default': '', 'another-resolve': ''}",
        ]
    )
    rule_runner.write_files(
        {
            "root1/thrift/no_namespace.thrift": "",
            "root1/thrift/namespace.thrift": "namespace py custom_namespace.module",
            "root1/thrift/BUILD": dedent(
                """\
                thrift_sources(
                    overrides={
                        "no_namespace.thrift": {"python_resolve": "another-resolve"}
                    },
                )
                """
            ),
            # These files will result in the same module name.
            "root1/foo/two_owners.thrift": "",
            "root1/foo/BUILD": "thrift_sources()",
            "root2/bar/two_owners.thrift": "",
            "root2/bar/BUILD": "thrift_sources()",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonThriftMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "custom_namespace.module.constants": providers(
                    [Address("root1/thrift", relative_file_path="namespace.thrift")]
                ),
                "custom_namespace.module.ttypes": providers(
                    [Address("root1/thrift", relative_file_path="namespace.thrift")]
                ),
                "two_owners.constants": providers(
                    [
                        Address("root1/foo", relative_file_path="two_owners.thrift"),
                        Address("root2/bar", relative_file_path="two_owners.thrift"),
                    ]
                ),
                "two_owners.ttypes": providers(
                    [
                        Address("root1/foo", relative_file_path="two_owners.thrift"),
                        Address("root2/bar", relative_file_path="two_owners.thrift"),
                    ]
                ),
            },
            "another-resolve": {
                "no_namespace.constants": providers(
                    [Address("root1/thrift", relative_file_path="no_namespace.thrift")]
                ),
                "no_namespace.ttypes": providers(
                    [Address("root1/thrift", relative_file_path="no_namespace.thrift")]
                ),
            },
        },
    )
