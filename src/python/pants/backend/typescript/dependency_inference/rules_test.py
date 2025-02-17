# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.experimental.typescript import register as typescript_register
from pants.backend.javascript import package_json
from pants.backend.javascript.dependency_inference.rules import InferNodePackageDependenciesRequest
from pants.backend.javascript.dependency_inference.rules import (
    rules as js_dependency_inference_rules,
)
from pants.backend.javascript.package_json import AllPackageJson
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.backend.tsx.target_types import TSXSourcesGeneratorTarget, TSXSourceTarget
from pants.backend.typescript.dependency_inference.rules import (
    InferTypeScriptDependenciesRequest,
    TypeScriptSourceInferenceFieldSet,
)
from pants.backend.typescript.dependency_inference.rules import (
    rules as ts_dependency_inference_rules,
)
from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptSourceTarget,
)
from pants.build_graph.address import Address
from pants.core.util_rules.unowned_dependency_behavior import UnownedDependencyError
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *package_json.rules(),
            *js_dependency_inference_rules(),
            *ts_dependency_inference_rules(),
            QueryRule(AllPackageJson, ()),
            QueryRule(Owners, (OwnersRequest,)),
            QueryRule(InferredDependencies, (InferNodePackageDependenciesRequest,)),
            QueryRule(InferredDependencies, (InferTypeScriptDependenciesRequest,)),
        ],
        target_types=[
            *package_json.target_types(),
            *typescript_register.target_types(),
            TypeScriptSourceTarget,
            TypeScriptSourcesGeneratorTarget,
            TSXSourceTarget,
            TSXSourcesGeneratorTarget,
            JSSourceTarget,
            JSSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_infers_typescript_file_imports_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/ts/BUILD": dedent(
                """\
                typescript_sources()
                tsx_sources(name='tsx')
                javascript_sources(name='js')
                """
            ),
            "src/ts/index.ts": dedent(
                """\
                import { x } from "./localModuleA";
                import { y } from "./localModuleB";
                import { x, y } from "./localModuleE";
                import x from "./localModuleF";
                import * as D from "./localModuleD";
                import { x as z } from "./localModuleG";
                import type x from "./localModuleH";

                // You can import a file and not include any variables
                import "./localModuleC";

                // You can import a JS module in a TypeScript module
                import { x } from './localModuleJs';

                // You can import a TSX module in a TypeScript module
                import { x } from './localModuleTsx';
                """
            ),
            "src/ts/localModuleA.ts": "",
            "src/ts/localModuleB.ts": "",
            "src/ts/localModuleC.ts": "",
            "src/ts/localModuleD.ts": "",
            "src/ts/localModuleE.ts": "",
            "src/ts/localModuleF.ts": "",
            "src/ts/localModuleG.ts": "",
            "src/ts/localModuleH.ts": "",
            "src/ts/localModuleJs.js": "",
            "src/ts/localModuleTsx.tsx": "",
        }
    )

    index_tgt = rule_runner.get_target(Address("src/ts", relative_file_path="index.ts"))
    addresses = rule_runner.request(
        InferredDependencies,
        [InferTypeScriptDependenciesRequest(TypeScriptSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {
        Address("src/ts", relative_file_path="localModuleA.ts"),
        Address("src/ts", relative_file_path="localModuleB.ts"),
        Address("src/ts", relative_file_path="localModuleC.ts"),
        Address("src/ts", relative_file_path="localModuleD.ts"),
        Address("src/ts", relative_file_path="localModuleE.ts"),
        Address("src/ts", relative_file_path="localModuleF.ts"),
        Address("src/ts", relative_file_path="localModuleG.ts"),
        Address("src/ts", relative_file_path="localModuleH.ts"),
        Address("src/ts", relative_file_path="localModuleJs.js", target_name="js"),
        Address("src/ts", relative_file_path="localModuleTsx.tsx", target_name="tsx"),
    }


def test_infers_typescript_file_imports_dependencies_parent_dirs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/ts/BUILD": "typescript_sources()",
            "src/ts/subdir1/subdir2/BUILD": "typescript_sources()",
            "src/ts/subdir1/BUILD": "typescript_sources()",
            "src/ts/subdir1/subdir2/index.ts": dedent(
                """\
                import { x } from "../../localModuleA";
                import { y } from "../../localModuleB";
                import { w } from "../localModuleC";

                // not a file-based import, can't map to a file on disk
                import { z } from "localModuleD";
                """
            ),
            "src/ts/localModuleA.ts": "",
            "src/ts/localModuleB.ts": "",
            "src/ts/subdir1/localModuleC.ts": "",
            "src/ts/localModuleD.ts": "",
        }
    )

    index_tgt = rule_runner.get_target(
        Address("src/ts/subdir1/subdir2", relative_file_path="index.ts")
    )
    addresses = rule_runner.request(
        InferredDependencies,
        [InferTypeScriptDependenciesRequest(TypeScriptSourceInferenceFieldSet.create(index_tgt))],
    ).include

    assert set(addresses) == {
        Address("src/ts", relative_file_path="localModuleA.ts"),
        Address("src/ts", relative_file_path="localModuleB.ts"),
        Address("src/ts/subdir1", relative_file_path="localModuleC.ts"),
    }


def test_unmatched_ts_dependencies_error_unowned_behaviour(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--nodejs-infer-unowned-dependency-behavior=error"])
    rule_runner.write_files(
        {
            "root/project/src/modA.ts": "",
            "root/project/src/index.ts": dedent(
                """\
                import { foo } from "./bar";
                import { something } from "./modA";
                """
            ),
            "root/project/src/BUILD": "typescript_sources()",
        }
    )

    root_index_tgt = rule_runner.get_target(
        Address("root/project/src", relative_file_path="index.ts")
    )

    with engine_error(UnownedDependencyError, contains="./bar"):
        rule_runner.request(
            InferredDependencies,
            [
                InferTypeScriptDependenciesRequest(
                    TypeScriptSourceInferenceFieldSet.create(root_index_tgt)
                )
            ],
        )

    # having unowned dependencies should not lead to errors
    rule_runner.set_options(["--nodejs-infer-unowned-dependency-behavior=warning"])
    addresses = rule_runner.request(
        InferredDependencies,
        [
            InferTypeScriptDependenciesRequest(
                TypeScriptSourceInferenceFieldSet.create(root_index_tgt)
            )
        ],
    ).include
    assert list(addresses)[0].spec == Address("root/project/src/modA.ts").spec_path
