# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.explorer.graphql.setup import create_schema
from pants.backend.explorer.rules import rules
from pants.engine.explorer import RequestState
from pants.engine.target import RegisteredTargetTypes
from pants.help.help_info_extracter import AllHelpInfo, HelpInfoExtracter
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture(scope="session")
def schema():
    return create_schema()


@pytest.fixture(scope="session")
def query() -> str:
    return dedent(
        """\
        query TestQuery($name: String, $limit: Int) {
          rules(query:{nameRe: $name, limit: $limit}) {
            name
          }
        }
        """
    )


@pytest.fixture(scope="session")
def context(all_help_info: AllHelpInfo, rule_runner: RuleRunner):
    print(all_help_info.name_to_rule_info.keys())
    return dict(
        pants_request_state=RequestState(
            all_help_info, rule_runner.build_config, rule_runner.scheduler
        )
    )


@pytest.fixture(scope="session")
def all_help_info(rule_runner: RuleRunner) -> AllHelpInfo:
    def fake_consumed_scopes_mapper(scope: str) -> tuple[str, ...]:
        return ("somescope", f"used_by_{scope or 'GLOBAL_SCOPE'}")

    return HelpInfoExtracter.get_all_help_info(
        options=rule_runner.options_bootstrapper.full_options(rule_runner.build_config),
        union_membership=rule_runner.union_membership,
        consumed_scopes_mapper=fake_consumed_scopes_mapper,
        registered_target_types=RegisteredTargetTypes.create(rule_runner.build_config.target_types),
        build_configuration=rule_runner.build_config,
    )


@pytest.fixture(scope="session")
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=rules(),
    )


@pytest.mark.parametrize(
    "variables, expected_data",
    [
        (
            {"name": r"\.explorer\."},
            {"rules": [{"name": "pants.backend.explorer.rules.validate_explorer_dependencies"}]},
        ),
    ],
)
def test_rules_query(schema, query, variables, expected_data, context) -> None:
    actual_result = schema.execute_sync(query, variable_values=variables, context_value=context)
    assert actual_result.errors is None
    assert actual_result.data == expected_data
