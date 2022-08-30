# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.build_graph.address import Address
from pants.core.util_rules import environments
from pants.core.util_rules.environments import (
    AllEnvironments,
    AmbiguousEnvironmentError,
    ChosenLocalEnvironment,
    LocalEnvironmentTarget,
    NoCompatibleEnvironmentError,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *environments.rules(),
            QueryRule(AllEnvironments, []),
            QueryRule(ChosenLocalEnvironment, []),
        ],
        target_types=[LocalEnvironmentTarget],
    )


def test_all_environments(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                _local_environment(name='e1')
                _local_environment(name='e2')
                _local_environment(name='no-alias')
                """
            )
        }
    )
    rule_runner.set_options(["--environments-preview-aliases={'e1': '//:e1', 'e2': '//:e2'}"])
    result = rule_runner.request(AllEnvironments, [])
    assert result == AllEnvironments(
        {
            "e1": LocalEnvironmentTarget({}, Address("", target_name="e1")),
            "e2": LocalEnvironmentTarget({}, Address("", target_name="e2")),
        }
    )


def test_choose_local_environment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                _local_environment(name='e1')
                _local_environment(name='e2')
                _local_environment(name='not-compatible', compatible_platforms=[])
                """
            )
        }
    )

    def get_env() -> ChosenLocalEnvironment:
        return rule_runner.request(ChosenLocalEnvironment, [])

    # If `--aliases` is not set, do not choose an environment.
    assert get_env().tgt is None

    rule_runner.set_options(["--environments-preview-aliases={'e': '//:e1'}"])
    assert get_env().tgt == LocalEnvironmentTarget({}, Address("", target_name="e1"))

    # Error if `--aliases` set, but no compatible platforms
    rule_runner.set_options(["--environments-preview-aliases={'e': '//:not-compatible'}"])
    with engine_error(NoCompatibleEnvironmentError):
        get_env()

    # Error if >1 compatible targets.
    rule_runner.set_options(["--environments-preview-aliases={'e1': '//:e1', 'e2': '//:e2'}"])
    with engine_error(AmbiguousEnvironmentError):
        get_env()
