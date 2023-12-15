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
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import RuleRunner


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
            JSSourceTarget,
            JSSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_infers_typescript_file_imports_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/ts/BUILD": "typescript_sources()",
            "src/ts/index.ts": dedent(
                """\
                import { x } from "./localModuleA";
                import { y } from "./localModuleB";
                """
            ),
            "src/ts/localModuleA.ts": "",
            "src/ts/localModuleB.ts": "",
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
    }
