# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoModule, GoModuleSources, GoPackage
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.rules import QueryRule
from pants.engine.target import Dependencies, DependenciesRequest, Target, UnexpandedTargets
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *target_type_rules.rules(),
            QueryRule(Addresses, (DependenciesRequest,)),
            QueryRule(UnexpandedTargets, (Addresses,)),
        ],
        target_types=[GoPackage, GoModule],
    )


def assert_go_module_address(rule_runner: RuleRunner, target: Target, expected_address: Address):
    addresses = rule_runner.request(Addresses, [DependenciesRequest(target[Dependencies])])
    targets = rule_runner.request(UnexpandedTargets, [addresses])
    go_module_targets = [tgt for tgt in targets if tgt.has_field(GoModuleSources)]
    assert len(go_module_targets) == 1
    assert go_module_targets[0].address == expected_address


def test_go_module_dependency_injection(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("foo", "go_module()")
    rule_runner.write_files(
        {
            "foo/pkg/foo.go": "package pkg\n",
            "foo/go.mod": "module foo\n",
            "foo/go.sum": "",
            "foo/bar/src.go": "package bar\n",
        }
    )
    rule_runner.add_to_build_file("foo/pkg", "go_package()")
    rule_runner.add_to_build_file("foo/bar", "go_module(name='mod')\ngo_package(name='pkg')\n")

    target = rule_runner.get_target(Address("foo/pkg", target_name="pkg"))
    assert_go_module_address(rule_runner, target, Address("foo"))

    target = rule_runner.get_target(Address("foo/bar", target_name="pkg"))
    assert_go_module_address(rule_runner, target, Address("foo/bar", target_name="mod"))
