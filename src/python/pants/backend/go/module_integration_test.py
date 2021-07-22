# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import pytest

from pants.backend.go import module
from pants.backend.go.module import ResolvedGoModule, ResolveGoModuleRequest
from pants.backend.go.target_types import GoExternalModule, GoModule, GoPackage
from pants.build_graph.address import Address
from pants.core.util_rules import external_tool, source_files
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *module.rules(),
            QueryRule(ResolvedGoModule, [ResolveGoModuleRequest]),
        ],
        target_types=[GoPackage, GoModule, GoExternalModule],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.experimental.go"])
    return rule_runner


def test_basic_parse_go_mod() -> None:
    content = b"module go.example.com/foo\ngo 1.16\nrequire github.com/golang/protobuf v1.4.2\n"
    module_path, minimum_go_version = module.basic_parse_go_mod(content)
    assert module_path == "go.example.com/foo"
    assert minimum_go_version == "1.16"


def test_resolve_go_module(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("foo", "go_module(name='mod')\ngo_package(name='pkg')\n")
    rule_runner.write_files(
        {
            "foo/pkg/foo.go": "package pkg\n",
            "foo/go.mod": "module go.example.com/foo\ngo 1.16\nrequire github.com/golang/protobuf v1.4.2\n",
            "foo/go.sum": "",
            "foo/main.go": "package main\nfunc main() { }\n",
        }
    )
    resolved_go_module = rule_runner.request(
        ResolvedGoModule, [ResolveGoModuleRequest(Address("foo", target_name="mod"))]
    )
    assert resolved_go_module.import_path == "go.example.com/foo"
    assert resolved_go_module.minimum_go_version == "1.16"
    assert len(resolved_go_module.modules) > 0
    found_protobuf_module = False
    for module_descriptor in resolved_go_module.modules:
        if module_descriptor.module_path == "github.com/golang/protobuf":
            found_protobuf_module = True
    assert found_protobuf_module
