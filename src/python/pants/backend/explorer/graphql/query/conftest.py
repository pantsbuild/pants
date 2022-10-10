# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.explorer.graphql.rules import rules
from pants.backend.explorer.graphql.setup import create_schema
from pants.backend.explorer.rules import validate_explorer_dependencies
from pants.backend.project_info import peek
from pants.engine.environment import EnvironmentName
from pants.engine.explorer import RequestState
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.help.help_info_extracter import AllHelpInfo, HelpInfoExtracter
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture(scope="session")
def schema():
    return create_schema()


@pytest.fixture
def context(all_help_info: AllHelpInfo, rule_runner: RuleRunner) -> dict:
    return dict(
        pants_request_state=RequestState(
            all_help_info,
            rule_runner.build_config,
            rule_runner.scheduler,
            env_name=EnvironmentName(None),
        )
    )


@pytest.fixture
def all_help_info(rule_runner: RuleRunner) -> AllHelpInfo:
    def fake_consumed_scopes_mapper(scope: str) -> tuple[str, ...]:
        return ("somescope", f"used_by_{scope or 'GLOBAL_SCOPE'}")

    return HelpInfoExtracter.get_all_help_info(
        options=rule_runner.options_bootstrapper.full_options(
            rule_runner.build_config, union_membership=UnionMembership({})
        ),
        union_membership=rule_runner.union_membership,
        consumed_scopes_mapper=fake_consumed_scopes_mapper,
        registered_target_types=RegisteredTargetTypes.create(rule_runner.build_config.target_types),
        build_configuration=rule_runner.build_config,
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(
            validate_explorer_dependencies,
            *peek.rules(),
            *rules(),
        ),
        target_types=(DockerImageTarget,),
    )


@pytest.fixture(scope="session")
def queries() -> str:
    return dedent(
        """\
        query TestRulesQuery($name: String, $limit: Int) {
          rules(query:{nameRe: $name, limit: $limit}) { name }
        }

        query TestTargetsQuery($specs: [String!], $targetType: String, $limit: Int) {
          targets(query:{specs: $specs, targetType: $targetType, limit: $limit}) { targetType }
        }

        query TestTargetTypesQuery($alias: String, $limit: Int) {
          targetTypes(query:{aliasRe: $alias, limit: $limit}) { alias }
        }
        """
    )
