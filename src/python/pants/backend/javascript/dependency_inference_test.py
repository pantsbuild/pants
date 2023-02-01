# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json

import pytest

from pants.backend.javascript import dependency_inference, package_json
from pants.backend.javascript.dependency_inference import (
    InferPackageJsonDependenciesRequest,
    PackageJsonInferenceFieldSet,
)
from pants.backend.javascript.package_json import (
    AllPackageJson,
    PackageJson,
    PackageJsonTarget,
    ReadPackageJsonRequest,
)
from pants.build_graph.address import Address
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies, Target
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package_json.rules(),
            *dependency_inference.rules(),
            QueryRule(AllPackageJson, ()),
            QueryRule(Owners, (OwnersRequest,)),
            QueryRule(PackageJson, (ReadPackageJsonRequest,)),
            QueryRule(InferredDependencies, (InferPackageJsonDependenciesRequest,)),
        ],
        target_types=[PackageJsonTarget],
    )


def given_package(name: str, version: str) -> str:
    return json.dumps({"name": name, "version": version})


def given_package_with_workspaces(name: str, version: str, *workspaces: str) -> str:
    return json.dumps({"name": name, "version": version, "workspaces": list(workspaces)})


def get_inferred_package_jsons_address(
    rule_runner: RuleRunner, tgt: Target
) -> FrozenOrderedSet[Address]:
    return rule_runner.request(
        InferredDependencies,
        [InferPackageJsonDependenciesRequest(PackageJsonInferenceFieldSet.create(tgt))],
    ).include


def test_infers_workspace_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_workspaces("ham", "0.0.1", "bar"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    tgt = rule_runner.get_target(Address("src/js"))

    inferred = get_inferred_package_jsons_address(rule_runner, tgt)

    assert set(inferred) == {Address("src/js/bar")}


def test_infers_nested_workspace_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_workspaces("ham", "0.0.1", "bar"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package_with_workspaces("spam", "0.0.2", "baz"),
            "src/js/bar/baz/BUILD": "package_json()",
            "src/js/bar/baz/package.json": given_package("egg", "0.0.3"),
        }
    )

    root_tgt = rule_runner.get_target(Address("src/js"))
    child_tgt = rule_runner.get_target(Address("src/js/bar"))
    grandchild_tgt = rule_runner.get_target(Address("src/js/bar/baz"))

    inferred_from_root = get_inferred_package_jsons_address(rule_runner, root_tgt)
    inferred_from_child = get_inferred_package_jsons_address(rule_runner, child_tgt)
    inferred_from_grandchild = get_inferred_package_jsons_address(rule_runner, grandchild_tgt)

    assert set(inferred_from_root) == {Address("src/js/bar")}
    assert set(inferred_from_child) == {Address("src/js/bar/baz")}
    assert not inferred_from_grandchild
