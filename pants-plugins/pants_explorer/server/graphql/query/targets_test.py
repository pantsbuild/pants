# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.testutil.rule_runner import RuleRunner


@pytest.mark.parametrize(
    "variables, expected_data",
    [
        (
            {},
            {"targets": [{"targetType": "docker_image"}]},
        ),
        (
            {"limit": 0},
            {"targets": []},
        ),
        (
            {"specs": ["src/test:test"]},
            {"targets": [{"targetType": "docker_image"}]},
        ),
    ],
)
async def test_targets_query(
    rule_runner: RuleRunner,
    schema,
    queries: str,
    variables: dict,
    expected_data: dict,
    context: dict,
) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": "docker_image()",
            "src/test/Dockerfile": "",
        }
    )
    with rule_runner.pushd():
        actual_result = await schema.execute(
            queries, variable_values=variables, context_value=context, operation_name="TestTargetsQuery"
        )
    assert actual_result.errors is None
    assert actual_result.data == expected_data


@pytest.mark.parametrize(
    "variables, expected_data",
    [
        (
            {},
            {
                "targetTypes": [
                    {"alias": "docker_image"},
                ]
            },
        ),
        (
            {"limit": 0},
            {"targetTypes": []},
        ),
    ],
)
async def test_target_types_query(
    rule_runner: RuleRunner,
    schema,
    queries: str,
    variables: dict,
    expected_data: dict,
    context: dict,
) -> None:
    actual_result = await schema.execute(
        queries,
        variable_values=variables,
        context_value=context,
        operation_name="TestTargetTypesQuery",
    )
    assert actual_result.errors is None
    assert actual_result.data == expected_data
