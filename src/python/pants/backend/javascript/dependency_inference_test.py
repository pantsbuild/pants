# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from textwrap import dedent

import pytest

from pants.backend.javascript import dependency_inference, package_json
from pants.backend.javascript.dependency_inference import (
    InferJSDependenciesRequest,
    InferNodePackageDependenciesRequest,
    JSSourceInferenceFieldSet,
    NodePackageInferenceFieldSet,
)
from pants.backend.javascript.package_json import AllPackageJson
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
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
            QueryRule(InferredDependencies, (InferNodePackageDependenciesRequest,)),
        ],
        target_types=[*package_json.target_types(), JSSourceTarget, JSSourcesGeneratorTarget],
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
        [InferNodePackageDependenciesRequest(NodePackageInferenceFieldSet.create(tgt))],
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
    tgt = rule_runner.get_target(Address("src/js/bar", generated_name="spam"))

    inferred = get_inferred_package_jsons_address(rule_runner, tgt)

    assert set(inferred) == {Address("src/js", generated_name="ham")}


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

    root_tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    child_tgt = rule_runner.get_target(Address("src/js/bar", generated_name="spam"))
    grandchild_tgt = rule_runner.get_target(Address("src/js/bar/baz", generated_name="egg"))

    inferred_from_root = get_inferred_package_jsons_address(rule_runner, root_tgt)
    inferred_from_child = get_inferred_package_jsons_address(rule_runner, child_tgt)
    inferred_from_grandchild = get_inferred_package_jsons_address(rule_runner, grandchild_tgt)

    assert not inferred_from_root
    assert set(inferred_from_child) == {Address("src/js", generated_name="ham")}
    assert set(inferred_from_grandchild) == {Address("src/js/bar", generated_name="spam")}


def test_infers_esmodule_js_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "javascript_sources()",
            "src/js/index.mjs": dedent(
                """\
                import fs from "fs";
                import { x } from "./xes.mjs";
                """
            ),
            "src/js/xes.mjs": "",
        }
    )

    index_tgt = rule_runner.get_target(Address("src/js", relative_file_path="index.mjs"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {Address("src/js", relative_file_path="xes.mjs")}


def test_infers_esmodule_js_dependencies_from_ancestor_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "javascript_sources()",
            "src/js/a/BUILD": "javascript_sources()",
            "src/js/a/index.mjs": dedent(
                """\
                import fs from "fs";
                import { x } from "../xes.mjs";
                """
            ),
            "src/js/xes.mjs": "",
        }
    )

    index_tgt = rule_runner.get_target(Address("src/js/a", relative_file_path="index.mjs"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {Address("src/js", relative_file_path="xes.mjs")}


def test_infers_commonjs_js_dependencies_from_ancestor_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "javascript_sources()",
            "src/js/a/BUILD": "javascript_sources()",
            "src/js/a/index.cjs": dedent(
                """\
                const fs = require("fs");
                const { x } = require("../xes.cjs");
                """
            ),
            "src/js/xes.cjs": "",
        }
    )

    index_tgt = rule_runner.get_target(Address("src/js/a", relative_file_path="index.cjs"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {Address("src/js", relative_file_path="xes.cjs")}
