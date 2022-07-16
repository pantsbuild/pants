# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.openapi import dependency_inference
from pants.backend.openapi.dependency_inference import (
    InferOpenApiDefinitionDependenciesRequest,
    InferOpenApiSourceDependenciesRequest,
    OpenApiDefinitionDependenciesInferenceFieldSet,
    OpenApiSourceDependenciesInferenceFieldSet,
)
from pants.backend.openapi.target_types import (
    OpenApiDefinitionGeneratorTarget,
    OpenApiSourceGeneratorTarget,
)
from pants.build_graph.address import Address
from pants.core.util_rules import external_tool
from pants.engine.rules import QueryRule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[OpenApiDefinitionGeneratorTarget, OpenApiSourceGeneratorTarget],
        rules=[
            *external_tool.rules(),
            *dependency_inference.rules(),
            UnionRule(InferDependenciesRequest, InferOpenApiDefinitionDependenciesRequest),
            UnionRule(InferDependenciesRequest, InferOpenApiSourceDependenciesRequest),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
        ],
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.experimental.openapi"],
    )
    return rule_runner


def test_definition_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/openapi/foo/BUILD": 'openapi_sources()\nopenapi_definitions(name="openapi")\n',
            "src/openapi/foo/openapi.json": "{}",
        }
    )

    target = rule_runner.get_target(
        Address("src/openapi/foo", target_name="openapi", relative_file_path="openapi.json")
    )
    inferred_deps = rule_runner.request(
        InferredDependencies,
        [
            InferOpenApiDefinitionDependenciesRequest(
                OpenApiDefinitionDependenciesInferenceFieldSet.create(target)
            )
        ],
    )
    assert inferred_deps == InferredDependencies(
        FrozenOrderedSet(
            [
                Address("src/openapi/foo", relative_file_path="openapi.json"),
            ]
        ),
    )


def test_source_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/openapi/foo/BUILD": "openapi_sources()\n",
            "src/openapi/foo/openapi.json": textwrap.dedent(
                """\
            {
                "foo": {
                    "$ref": "bar/models.json"
                },
                "bar": {
                    "$ref": "../bar/models.yaml"
                }
            }
            """
            ),
            "src/openapi/foo/bar/BUILD": "openapi_sources()\n",
            "src/openapi/foo/bar/models.json": "{}",
            "src/openapi/bar/subdir/BUILD": "openapi_sources()\n",
            "src/openapi/bar/subdir/models.yaml": "$ref: ../models.yaml\n",
            "src/openapi/bar/BUILD": "openapi_sources()\n",
            "src/openapi/bar/models.yaml": "{}",
        }
    )

    target = rule_runner.get_target(Address("src/openapi/foo", relative_file_path="openapi.json"))
    inferred_deps = rule_runner.request(
        InferredDependencies,
        [
            InferOpenApiSourceDependenciesRequest(
                OpenApiSourceDependenciesInferenceFieldSet.create(target)
            )
        ],
    )
    assert inferred_deps == InferredDependencies(
        FrozenOrderedSet(
            [
                Address("src/openapi/bar", relative_file_path="models.yaml"),
                Address("src/openapi/foo/bar", relative_file_path="models.json"),
            ]
        ),
    )

    target = rule_runner.get_target(
        Address("src/openapi/bar/subdir", relative_file_path="models.yaml")
    )
    inferred_deps = rule_runner.request(
        InferredDependencies,
        [
            InferOpenApiSourceDependenciesRequest(
                OpenApiSourceDependenciesInferenceFieldSet.create(target)
            )
        ],
    )
    assert inferred_deps == InferredDependencies(
        FrozenOrderedSet(
            [
                Address("src/openapi/bar", relative_file_path="models.yaml"),
            ]
        ),
    )
