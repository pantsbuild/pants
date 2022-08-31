# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.build_graph.address import Address, ResolveError
from pants.core.util_rules import environments
from pants.core.util_rules.environments import (
    LOCAL_ENVIRONMENT_MATCHER,
    AllEnvironmentTargets,
    AmbiguousEnvironmentError,
    ChosenLocalEnvironmentAlias,
    LocalEnvironmentTarget,
    NoCompatibleEnvironmentError,
    ResolvedEnvironmentAlias,
    ResolvedEnvironmentRequest,
    ResolvedEnvironmentTarget,
    UnrecognizedEnvironmentError,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *environments.rules(),
            QueryRule(AllEnvironmentTargets, []),
            QueryRule(ChosenLocalEnvironmentAlias, []),
            QueryRule(ResolvedEnvironmentTarget, [ResolvedEnvironmentAlias]),
            QueryRule(ResolvedEnvironmentAlias, [ResolvedEnvironmentRequest]),
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
    result = rule_runner.request(AllEnvironmentTargets, [])
    assert result == AllEnvironmentTargets(
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

    def get_env() -> ResolvedEnvironmentTarget:
        alias = rule_runner.request(ChosenLocalEnvironmentAlias, [])
        return rule_runner.request(ResolvedEnvironmentTarget, [ResolvedEnvironmentAlias(alias.val)])

    # If `--aliases` is not set, do not choose an environment.
    assert get_env().val is None

    rule_runner.set_options(["--environments-preview-aliases={'e': '//:e1'}"])
    assert get_env().val == LocalEnvironmentTarget({}, Address("", target_name="e1"))

    # Error if `--aliases` set, but no compatible platforms
    rule_runner.set_options(["--environments-preview-aliases={'e': '//:not-compatible'}"])
    with engine_error(NoCompatibleEnvironmentError):
        get_env()

    # Error if >1 compatible targets.
    rule_runner.set_options(["--environments-preview-aliases={'e1': '//:e1', 'e2': '//:e2'}"])
    with engine_error(AmbiguousEnvironmentError):
        get_env()


def test_resolve_environment_alias(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                _local_environment(name='local')
                # Intentionally set this to no platforms so that it cannot be autodiscovered.
                _local_environment(name='hardcoded', compatible_platforms=[])
                """
            )
        }
    )

    def get_alias(v: str) -> ResolvedEnvironmentAlias:
        return rule_runner.request(
            ResolvedEnvironmentAlias, [ResolvedEnvironmentRequest(v, description_of_origin="foo")]
        )

    # If `--aliases` is not set, and the local matcher is used, do not choose an environment.
    assert get_alias(LOCAL_ENVIRONMENT_MATCHER).val is None
    # Else, error for unrecognized aliases.
    with engine_error(UnrecognizedEnvironmentError):
        get_alias("hardcoded")

    rule_runner.set_options(
        ["--environments-preview-aliases={'local': '//:local', 'hardcoded': '//:hardcoded'}"]
    )
    assert get_alias(LOCAL_ENVIRONMENT_MATCHER).val == "local"
    assert get_alias("hardcoded").val == "hardcoded"
    with engine_error(UnrecognizedEnvironmentError):
        get_alias("fake")


def test_resolve_environment_tgt(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": "_local_environment(name='env')"})
    rule_runner.set_options(
        ["--environments-preview-aliases={'env': '//:env', 'bad-address': '//:fake'}"]
    )

    def get_tgt(v: str | None) -> ResolvedEnvironmentTarget:
        return rule_runner.request(ResolvedEnvironmentTarget, [ResolvedEnvironmentAlias(v)])

    assert get_tgt(None).val is None

    # If the alias is not defined, error.
    with engine_error(AssertionError):
        get_tgt("bad")

    assert get_tgt("env").val == LocalEnvironmentTarget({}, Address("", target_name="env"))
    with engine_error(ResolveError):
        get_tgt("bad-address")
