# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.build_graph.address import Address
from pants.core.util_rules import environments
from pants.core.util_rules.environments import ChosenLocalEnvironment, LocalEnvironmentTarget
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *environments.rules(),
            QueryRule(ChosenLocalEnvironment, []),
        ],
        target_types=[LocalEnvironmentTarget],
    )


def test_choose_local_environment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                _local_environment(name='local_env')
                """
            )
        }
    )
    # If `--platforms-to-local-environments` is not set, do not choose an environment.
    assert rule_runner.request(ChosenLocalEnvironment, []).tgt is None

    rule_runner.set_options(
        [
            # Note that we cannot inject the `Platform` to an arbitrary value: it will use the
            # platform of the test executor. So, we use the same environment for all platforms.
            (
                "--environments-preview-platforms-to-local-environment="
                + "{'macos_arm64': '//:local_env', "
                + "'macos_x86_64': '//:local_env', "
                + "'linux_arm64': '//:local_env', "
                + "'linux_x86_64': '//:local_env'}"
            ),
        ]
    )
    assert rule_runner.request(ChosenLocalEnvironment, []).tgt == LocalEnvironmentTarget(
        {}, Address("", target_name="local_env")
    )
