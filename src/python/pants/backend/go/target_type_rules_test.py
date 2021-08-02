# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.go import module, pkg, target_type_rules
from pants.backend.go.target_type_rules import InferGoDependenciesRequest
from pants.backend.go.target_types import GoModule, GoModuleSources, GoPackage, GoPackageSources
from pants.build_graph.address import Address
from pants.core.util_rules import external_tool, source_files
from pants.engine.addresses import Addresses
from pants.engine.rules import QueryRule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    InferredDependencies,
    Target,
    UnexpandedTargets,
)
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *module.rules(),
            *pkg.rules(),
            *target_type_rules.rules(),
            QueryRule(Addresses, (DependenciesRequest,)),
            QueryRule(UnexpandedTargets, (Addresses,)),
            QueryRule(InferredDependencies, (InferGoDependenciesRequest,)),
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
    rule_runner.write_files(
        {
            "foo/BUILD": "go_module()\n",
            "foo/go.mod": "module foo\n",
            "foo/go.sum": "",
            "foo/pkg/BUILD": "go_package()\n",
            "foo/pkg/foo.go": "package pkg\n",
            "foo/bar/BUILD": "go_module(name='mod')\ngo_package(name='pkg')\n",
            "foo/bar/go.mod": "module bar\n",
            "foo/bar/src.go": "package bar\n",
        }
    )

    target = rule_runner.get_target(Address("foo/pkg", target_name="pkg"))
    assert_go_module_address(rule_runner, target, Address("foo"))

    target = rule_runner.get_target(Address("foo/bar", target_name="pkg"))
    assert_go_module_address(rule_runner, target, Address("foo/bar", target_name="mod"))


def test_go_package_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        (
            {
                "foo/BUILD": "go_module()\n",
                "foo/go.mod": textwrap.dedent(
                    """\
                module go.example.com/foo
                go 1.16"""
                ),
                "foo/go.sum": "",
                "foo/pkg/BUILD": "go_package()\n",
                "foo/pkg/foo.go": textwrap.dedent(
                    """\
                package pkg
                func Grok() string {
                    return "Hello World"
                }"""
                ),
                "foo/cmd/BUILD": "go_package()\n",
                "foo/cmd/main.go": textwrap.dedent(
                    """\
                package main
                import (
                    "fmt"
                    "go.example.com/foo/pkg"
                )
                func main() {
                    fmt.Printf("%s\n", pkg.Grok())
                }"""
                ),
            }
        )
    )
    target = rule_runner.get_target(Address("foo/cmd"))
    inferred_deps = rule_runner.request(
        InferredDependencies, [InferGoDependenciesRequest(target[GoPackageSources])]
    )
    assert inferred_deps.dependencies == FrozenOrderedSet([Address("foo/pkg")])
    assert not inferred_deps.sibling_dependencies_inferrable
