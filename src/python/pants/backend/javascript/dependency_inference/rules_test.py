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
from pants.backend.jsx.target_types import JSXSourcesGeneratorTarget, JSXSourceTarget
from pants.backend.tsx.target_types import TSXSourcesGeneratorTarget, TSXSourceTarget
from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptSourceTarget,
)
from pants.build_graph.address import Address
from pants.core.util_rules.unowned_dependency_behavior import UnownedDependencyError
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies, Target
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *dependency_inference_rules(),
            QueryRule(AllPackageJson, ()),
            QueryRule(Owners, (OwnersRequest,)),
            QueryRule(InferredDependencies, (InferNodePackageDependenciesRequest,)),
            QueryRule(InferredDependencies, (InferJSDependenciesRequest,)),
        ],
        target_types=[
            *package_json.target_types(),
            JSSourceTarget,
            JSSourcesGeneratorTarget,
            JSXSourceTarget,
            JSXSourcesGeneratorTarget,
            TSXSourceTarget,
            TSXSourcesGeneratorTarget,
            TypeScriptSourceTarget,
            TypeScriptSourcesGeneratorTarget,
        ],
    )
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
            "src/js/BUILD": dedent(
                """\
                javascript_sources()
                jsx_sources(name='jsx')
                typescript_sources(name='ts')
                tsx_sources(name='tsx')
                """
            ),
            "src/js/index.mjs": dedent(
                """\
                import fs from "fs";
                import { x } from "./moduleA";
                import { y } from "./moduleB";
                import { z } from "./moduleC";
                import { w } from "./moduleD";
                import { u } from "./moduleE";
                """
            ),
            "src/js/moduleA.mjs": "",
            "src/js/moduleB.jsx": "",
            "src/js/moduleC.ts": "",
            "src/js/moduleD.tsx": "",
            "src/js/moduleE.d.ts": "",
        }
    )

    index_tgt = rule_runner.get_target(Address("src/js", relative_file_path="index.mjs"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {
        Address("src/js", relative_file_path="moduleA.mjs"),
        Address("src/js", relative_file_path="moduleB.jsx", target_name="jsx"),
        Address("src/js", relative_file_path="moduleC.ts", target_name="ts"),
        Address("src/js", relative_file_path="moduleD.tsx", target_name="tsx"),
        Address("src/js", relative_file_path="moduleE.d.ts", target_name="ts"),
    }


def test_infers_esmodule_js_dependencies_from_ancestor_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                javascript_sources()
                jsx_sources(name='jsx')
                typescript_sources(name='ts')
                tsx_sources(name='tsx')
                """
            ),
            "src/js/a/BUILD": "javascript_sources()",
            "src/js/a/index.mjs": dedent(
                """\
                import fs from "fs";
                import { x } from "../moduleA";
                import { y } from "../moduleB";
                import { z } from "../moduleC";
                import { w } from "../moduleD";
                import { u } from "../moduleE";
                """
            ),
            "src/js/moduleA.mjs": "",
            "src/js/moduleB.jsx": "",
            "src/js/moduleC.ts": "",
            "src/js/moduleD.tsx": "",
            "src/js/moduleE.d.ts": "",
        }
    )

    index_tgt = rule_runner.get_target(Address("src/js/a", relative_file_path="index.mjs"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {
        Address("src/js", relative_file_path="moduleA.mjs"),
        Address("src/js", relative_file_path="moduleB.jsx", target_name="jsx"),
        Address("src/js", relative_file_path="moduleC.ts", target_name="ts"),
        Address("src/js", relative_file_path="moduleD.tsx", target_name="tsx"),
        Address("src/js", relative_file_path="moduleE.d.ts", target_name="ts"),
    }


def test_infers_commonjs_js_dependencies_from_ancestor_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                javascript_sources()
                jsx_sources(name='jsx')
                typescript_sources(name='ts')
                tsx_sources(name='tsx')
                """
            ),
            "src/js/a/BUILD": "javascript_sources()",
            "src/js/a/index.cjs": dedent(
                """\
                const fs = require("fs");
                const { x } = require("../moduleA.cjs");
                const { y } = require("../moduleB.jsx");
                const { z } = require("../moduleC.ts");
                const { w } = require("../moduleD.tsx");
                """
            ),
            "src/js/moduleA.cjs": "",
            "src/js/moduleB.jsx": "",
            "src/js/moduleC.ts": "",
            "src/js/moduleD.tsx": "",
        }
    )

    index_tgt = rule_runner.get_target(Address("src/js/a", relative_file_path="index.cjs"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {
        Address("src/js", relative_file_path="moduleA.cjs"),
        Address("src/js", relative_file_path="moduleB.jsx", target_name="jsx"),
        Address("src/js", relative_file_path="moduleC.ts", target_name="ts"),
        Address("src/js", relative_file_path="moduleD.tsx", target_name="tsx"),
    }


def test_infers_js_dependencies_via_config(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "root/project/BUILD": "package_json()",
            "root/project/package.json": given_package("ham", "0.0.1", main="./src/index.js"),
            "root/project/jsconfig.json": json.dumps(
                {"compilerOptions": {"paths": {"*": ["./src/*"]}}}
            ),
            "root/project/src/BUILD": "javascript_sources()",
            "root/project/src/index.js": dedent(
                """\
                import button from "components/button.js";
                """
            ),
            "root/project/src/components/BUILD": "javascript_sources()",
            "root/project/src/components/button.js": "",
        }
    )

    index_tgt = rule_runner.get_target(Address("root/project/src", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {
        Address("root/project/src/components", relative_file_path="button.js")
    }


def test_infers_js_dependencies_via_config_and_extension_less_imports(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "root/project/BUILD": "package_json()",
            "root/project/package.json": given_package("ham", "0.0.1", main="./src/index.js"),
            "root/project/jsconfig.json": json.dumps(
                {"compilerOptions": {"paths": {"*": ["./src/*"]}}}
            ),
            "root/project/src/BUILD": "javascript_sources()",
            "root/project/src/index.js": dedent(
                """\
                import { Button } from "components";
                """
            ),
            "root/project/src/components/BUILD": "javascript_sources()",
            "root/project/src/components/index.js": "export { Button } from 'components/button'",
            "root/project/src/components/button.js": "",
        }
    )

    root_index_tgt = rule_runner.get_target(
        Address("root/project/src", relative_file_path="index.js")
    )

    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(root_index_tgt))],
    ).include

    assert set(addresses) == {Address("root/project/src/components", relative_file_path="index.js")}


def test_infers_js_dependencies_with_file_suffix(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "root/project/src/__generated__/BUILD": "javascript_sources()",
            "root/project/src/__generated__/moduleA.generated.js": "",
            "root/project/src/BUILD": "javascript_sources()",
            "root/project/src/index.js": dedent(
                """\
                import { x } from "./__generated__/moduleA.generated";
                """
            ),
        }
    )

    index_tgt = rule_runner.get_target(Address("root/project/src", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {
        Address("root/project/src/__generated__", relative_file_path="moduleA.generated.js"),
    }


def test_infers_js_dependencies_with_compiled_typescript_modules(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                javascript_sources()
                typescript_sources(name="ts")
                """
            ),
            "src/js/index.js": dedent(
                """\
                import { x } from "./moduleA";
                """
            ),
            "src/js/moduleA.ts": "",
            "src/js/moduleA.js": "",  # Compiled output from tsc
        }
    )

    index_tgt = rule_runner.get_target(Address("src/js", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {
        Address("src/js", relative_file_path="moduleA.js"),
        Address("src/js", target_name="ts", relative_file_path="moduleA.ts"),
    }


def test_unmatched_js_dependencies_and_error_unowned_behaviour(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--nodejs-infer-unowned-dependency-behavior=error"])
    rule_runner.write_files(
        {
            "root/project/BUILD": "package_json()",
            "root/project/package.json": given_package("ham", "0.0.1", main="./src/index.js"),
            "root/project/jsconfig.json": json.dumps(
                {"compilerOptions": {"paths": {"*": ["./src/*"]}}}
            ),
            "root/project/src/BUILD": "javascript_sources()",
            "root/project/src/index.js": dedent(
                """\
                import { Button } from "components";
                """
            ),
            "root/project/src/components/BUILD": "javascript_sources()",
            "root/project/src/components/button.js": "",
        }
    )

    root_index_tgt = rule_runner.get_target(
        Address("root/project/src", relative_file_path="index.js")
    )

    with engine_error(UnownedDependencyError, contains="components"):
        rule_runner.request(
            InferredDependencies,
            [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(root_index_tgt))],
        )


def test_unmatched_local_js_dependencies_fulfilled_with_third_party_package(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.set_options(["--nodejs-infer-unowned-dependency-behavior=error"])
    rule_runner.write_files(
        {
            "root/project/BUILD": "package_json()",
            "root/project/package.json": given_package(
                "ham", "0.0.1", main="./src/index.js", dependencies={"components": "*"}
            ),
            "root/project/jsconfig.json": json.dumps(
                {"compilerOptions": {"paths": {"*": ["./src/*"]}}}
            ),
            "root/project/src/BUILD": "javascript_sources()",
            "root/project/src/index.js": dedent(
                """\
                import { Button } from "components";
                """
            ),
        }
    )

    root_index_tgt = rule_runner.get_target(
        Address("root/project/src", relative_file_path="index.js")
    )

    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(root_index_tgt))],
    ).include

    assert set(addresses) == {Address("root/project", generated_name="components")}


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


def test_infers_scoped_third_party_package_json_field_js_source_dependency(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package(
                "ham", "0.0.1", main="lib/index.js", dependencies={"@angular/core": "14.0.0"}
            ),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": dedent(
                """\
                import { Component } from "@angular/core";
                """
            ),
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js/lib", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js", generated_name="__angular/core")}


def test_infers_third_party_package_json_field_js_source_dependency_with_subpath(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package(
                "ham", "0.0.1", main="lib/index.js", dependencies={"@mui/material": "5.0.0"}
            ),
            "src/js/lib/BUILD": "javascript_sources()",
            "src/js/lib/index.js": dedent(
                """\
                import Button from '@mui/material/Button';
                """
            ),
        }
    )

    pkg_tgt = rule_runner.get_target(Address("src/js/lib", relative_file_path="index.js"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferJSDependenciesRequest(JSSourceInferenceFieldSet.create(pkg_tgt))],
    ).include

    assert set(addresses) == {Address("src/js", generated_name="__mui/material")}


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
