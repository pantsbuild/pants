# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "variables, expected_data",
    [
        (
            {"name": r"pants_explorer\."},
            {
                "rules": [
                    {"name": "pants_explorer.server.graphql.rules.get_graphql_uvicorn_setup"},
                ]
            },
        ),
        (
            {"name": r"\.graphql\."},
            {
                "rules": [
                    {"name": "pants_explorer.server.graphql.rules.get_graphql_uvicorn_setup"},
                ]
            },
        ),
        (
            {"limit": 0},
            {"rules": []},
        ),
        (
            {"limit": 0},
            {"rules": []},
        ),
    ],
)
def test_rules_query(
    schema, queries: str, variables: dict, expected_data: dict, context: dict
) -> None:
    actual_result = schema.execute_sync(
        queries, variable_values=variables, context_value=context, operation_name="TestRulesQuery"
    )
    assert actual_result.errors is None
    assert actual_result.data == expected_data
