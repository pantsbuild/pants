# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.openapi import dependency_inference
from pants.backend.openapi.goals import tailor
from pants.backend.openapi.goals.tailor import PutativeOpenApiTargetsRequest
from pants.backend.openapi.target_types import (
    OpenApiDefinitionGeneratorTarget,
    OpenApiSourceGeneratorTarget,
)
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *dependency_inference.rules(),
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeOpenApiTargetsRequest, AllOwnedSources)),
        ],
        target_types=[OpenApiDefinitionGeneratorTarget, OpenApiSourceGeneratorTarget],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/owned/BUILD": "openapi_definitions()\n",
            "src/owned/openapi.json": '{"$ref": "foobar.json"}',
            "src/owned/foobar.json": "{}",
            "src/unowned/foobar.json": "{}",
            "src/unowned/openapi.json": '{"$ref": "subdir/foobar.json"}',
            "src/unowned/openapi.yaml": "{}",
            "src/unowned/subdir/foobar.json": '{"$ref": "../foobar.json"}',
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeOpenApiTargetsRequest(("src/owned", "src/unowned")),
            AllOwnedSources(["src/owned/openapi.json"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    OpenApiDefinitionGeneratorTarget,
                    "src/unowned",
                    "definition",
                    ["openapi.json", "openapi.yaml"],
                ),
                PutativeTarget.for_target_type(
                    OpenApiSourceGeneratorTarget,
                    "src/unowned",
                    "unowned",
                    ["foobar.json", "openapi.json", "openapi.yaml"],
                ),
                PutativeTarget.for_target_type(
                    OpenApiSourceGeneratorTarget,
                    "src/unowned/subdir",
                    "subdir",
                    ["foobar.json"],
                ),
                PutativeTarget.for_target_type(
                    OpenApiSourceGeneratorTarget,
                    "src/owned",
                    "owned",
                    ["foobar.json"],
                ),
            ]
        )
        == putative_targets
    )
