# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
    rules,
)
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            QueryRule(DockerBuildArgs, [DockerBuildArgsRequest]),
        ],
    )


@pytest.mark.parametrize(
    "build_args, extra_build_args, expected_build_args",
    [
        (
            (),
            None,
            (),
        ),
        (
            (""),
            None,
            (),
        ),
        (
            ("ARG1=val1",),
            None,
            ("ARG1=val1",),
        ),
        (
            ("ARG1=val1",),
            ("ARG2=val2",),
            (
                "ARG1=val1",
                "ARG2=val2",
            ),
        ),
        (
            ("ARG1=val1",),
            ("ARG1",),
            ("ARG1",),
        ),
        (
            ("ARG1",),
            ("ARG1=val1",),
            ("ARG1=val1",),
        ),
    ],
)
def test_docker_build_args_rule(
    rule_runner: RuleRunner,
    build_args: tuple[str, ...],
    extra_build_args: tuple[str, ...] | None,
    expected_build_args: tuple[str, ...],
) -> None:
    tgt = DockerImageTarget({"extra_build_args": extra_build_args}, address=Address("test"))
    rule_runner.set_options([f"--docker-build-args={build_arg}" for build_arg in build_args])
    res = rule_runner.request(DockerBuildArgs, [DockerBuildArgsRequest(tgt)])
    assert tuple(res) == expected_build_args
