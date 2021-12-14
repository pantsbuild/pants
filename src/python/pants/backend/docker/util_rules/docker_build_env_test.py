# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.docker_build_args import docker_build_args
from pants.backend.docker.util_rules.docker_build_env import (
    DockerBuildEnvironment,
    DockerBuildEnvironmentRequest,
    rules,
)
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            docker_build_args,
            *rules(),
            QueryRule(DockerBuildEnvironment, [DockerBuildEnvironmentRequest]),
        ],
    )


@pytest.mark.parametrize(
    "env_vars, build_args, expected_env_vars",
    [
        (
            (),
            (),
            {},
        ),
        (
            ("ENV1",),
            (),
            {"ENV1": "val1"},
        ),
        (
            ("ENV1=over1",),
            (),
            {"ENV1": "over1"},
        ),
        (
            (),
            ("ENV1=defined",),
            {},
        ),
        (
            (),
            ("ENV1",),
            {"ENV1": "val1"},
        ),
        (
            ("ENV1=over1",),
            ("ENV1",),
            {"ENV1": "over1"},
        ),
    ],
)
def test_docker_build_environment_vars_rule(
    rule_runner: RuleRunner,
    env_vars: tuple[str, ...],
    build_args: tuple[str, ...],
    expected_env_vars: dict[str, str],
) -> None:
    tgt = DockerImageTarget({"extra_build_args": build_args}, address=Address("test"))
    rule_runner.set_options(
        [f"--docker-env-vars={env_var}" for env_var in env_vars],
        env={
            "ENV1": "val1",
            "ENV2": "val2",
        },
    )
    res = rule_runner.request(DockerBuildEnvironment, [DockerBuildEnvironmentRequest(tgt)])
    assert res == DockerBuildEnvironment.create(expected_env_vars)
