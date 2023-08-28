# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
from textwrap import dedent

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.dependency_inference.rules import (
    InferJSDependenciesRequest,
    InferNodePackageDependenciesRequest,
    JSSourceInferenceFieldSet,
    NodePackageInferenceFieldSet,
)
from pants.backend.javascript.dependency_inference.rules import rules as dependency_inference_rules
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
    rule_runner = RuleRunner(
        rules=[
            *package_json.rules(),
            *dependency_inference_rules(),
            QueryRule(AllPackageJson, ()),
            QueryRule(Owners, (OwnersRequest,)),
            QueryRule(InferredDependencies, (InferNodePackageDependenciesRequest,)),
            QueryRule(InferredDependencies, (InferJSDependenciesRequest,)),
        ],
        target_types=[*package_json.target_types(), JSSourceTarget, JSSourcesGeneratorTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def given_package(name: str, version: str, **kwargs: str | dict[str, str]) -> str:
    return json.dumps({"name": name, "version": version, **kwargs})


def given_package_with_workspaces(name: str, version: str, *workspaces: str) -> str:
    return json.dumps({"name": name, "version": version, "workspaces": list(workspaces)})


def get_inferred_package_jsons_address(
    rule_runner: RuleRunner, tgt: Target
) -> FrozenOrderedSet[Address]:
    return rule_runner.request(
        InferredDependencies,
        [InferNodePackageDependenciesRequest(NodePackageInferenceFieldSet.create(tgt))],
    ).include


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


def test_infers_main_package_json_field_js_source_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package("ham", "0.0.1", main="lib/index.js"),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": "",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferNodePackageDependenciesRequest(NodePackageInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js/lib", relative_file_path="index.js")}


def test_infers_browser_package_json_field_js_source_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package("ham", "0.0.1", browser="lib/index.js"),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": "",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferNodePackageDependenciesRequest(NodePackageInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js/lib", relative_file_path="index.js")}


def test_infers_bin_package_json_field_js_source_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package("ham", "0.0.1", bin="bin/index.js"),
            "src/js/bin/BUILD": "javascript_sources()",
            "src/js/bin/index.js": "",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferNodePackageDependenciesRequest(NodePackageInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js/bin", relative_file_path="index.js")}


@pytest.mark.parametrize(
    "exports", ("lib/index.js", {".": "lib/index.js"}, {"lib": "lib/index.js"})
)
def test_infers_exports_package_json_field_js_source_dependency(
    rule_runner: RuleRunner, exports: str | dict[str, str]
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package("ham", "0.0.1", exports=exports),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": "",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferNodePackageDependenciesRequest(NodePackageInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js/lib", relative_file_path="index.js")}


@pytest.mark.parametrize("exports", ("lib/*.js", {".": "lib/*.js"}, {"lib": "lib/*.js"}))
def test_infers_exports_package_json_field_js_source_dependency_with_stars(
    rule_runner: RuleRunner, exports: str | dict[str, str]
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package("ham", "0.0.1", exports=exports),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": "",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferNodePackageDependenciesRequest(NodePackageInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js/lib", relative_file_path="index.js")}


@pytest.mark.parametrize("exports", ("lib/*.js", {".": "lib/*.js"}, {"lib": "lib/*"}))
def test_infers_exports_package_json_field_js_source_dependency_with_stars_interpreted_as_recursive(
    rule_runner: RuleRunner, exports: str | dict[str, str]
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package("ham", "0.0.1", exports=exports),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": "",
            "src/js/lib/subdir/BUILD": "javascript_sources()",
            "src/js/lib/subdir/index.js": "",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferNodePackageDependenciesRequest(NodePackageInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {
        Address("src/js/lib/subdir", relative_file_path="index.js"),
        Address("src/js/lib", relative_file_path="index.js"),
    }


def test_infers_third_party_package_json_field_js_source_dependency(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package(
                "ham", "0.0.1", main="lib/index.js", dependencies={"chalk": "5.0.2"}
            ),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": dedent(
                """\
                import chalk from "chalk";
                """
            ),
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js/lib", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js", generated_name="chalk")}


def test_infers_third_party_package_json_field_js_source_dependency_with_import_subpaths(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package(
                "ham",
                "0.0.1",
                main="lib/index.js",
                dependencies={"chalk": "5.0.2"},
                imports={"#myChalk": "chalk"},
            ),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": dedent(
                """\
                import chalk from "#myChalk";
                """
            ),
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js/lib", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js", generated_name="chalk")}


def test_infers_third_party_package_json_field_js_source_dependency_with_import_subpaths_with_star_replacements(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package(
                "ham",
                "0.0.1",
                main="lib/index.js",
                dependencies={"chalk": "5.0.2"},
                imports={"#myChalk/*.js": "chalk/stuff/*.js"},
            ),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": dedent(
                """\
                import chalk from "#myChalk/index.js";
                """
            ),
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js/lib", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js", generated_name="chalk")}


def test_infers_first_party_package_json_field_js_source_dependency(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": given_package("ham", "0.0.1"),
            "src/js/a/lib/BUILD": "javascript_sources()",
            "src/js/a/lib/index.js": dedent(
                """\
                import { x } from "spam";
                """
            ),
            "src/js/b/BUILD": "package_json()",
            "src/js/b/package.json": given_package("spam", "0.0.1"),
            "src/js/b/lib/BUILD": "javascript_sources()",
            "src/js/b/lib/index.js": "const x = 2;",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js/a/lib", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js/b", generated_name="spam")}


def test_infers_first_party_package_json_field_js_source_dependency_with_import_subpaths(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": given_package("ham", "0.0.1", imports={"#spam": "spam"}),
            "src/js/a/lib/BUILD": "javascript_sources()",
            "src/js/a/lib/index.js": dedent(
                """\
                import { x } from "#spam";
                """
            ),
            "src/js/b/BUILD": "package_json()",
            "src/js/b/package.json": given_package("spam", "0.0.1"),
            "src/js/b/lib/BUILD": "javascript_sources()",
            "src/js/b/lib/index.js": "const x = 2;",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js/a/lib", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js/b", generated_name="spam")}


def test_infers_first_party_package_json_field_js_source_dependency_with_starred_import_subpaths(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": given_package(
                "ham", "0.0.1", imports={"#spam/*.js": "spam/lib/*.js"}
            ),
            "src/js/a/lib/BUILD": "javascript_sources()",
            "src/js/a/lib/index.js": dedent(
                """\
                import { x } from "#spam/index.js";
                """
            ),
            "src/js/b/BUILD": "package_json()",
            "src/js/b/package.json": given_package("spam", "0.0.1"),
            "src/js/b/lib/BUILD": "javascript_sources()",
            "src/js/b/lib/index.js": "const x = 2;",
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js/a/lib", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js/b", generated_name="spam")}
