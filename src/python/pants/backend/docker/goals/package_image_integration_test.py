# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.docker.goals.package_image import DockerFieldSet
from pants.backend.docker.rules import rules as docker_rules
from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.python.util_rules import pex
from pants.core.goals.package import BuiltPackage
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *docker_rules(),
            *parser_rules(),
            *pex.rules(),
            *source_files_rules(),
            QueryRule(BuiltPackage, [DockerFieldSet]),
        ],
        target_types=[DockerImageTarget],
    )


def run_docker(
    rule_runner: RuleRunner,
    target: Target,
    *,
    extra_args: list[str] | None = None,
) -> BuiltPackage:
    rule_runner.set_options(
        extra_args or (),
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    result = rule_runner.request(
        BuiltPackage,
        [DockerFieldSet.create(target)],
    )
    return result


def test_docker_build(rule_runner) -> None:
    """This test requires a running docker daemon."""
    rule_runner.write_files(
        {
            "src/BUILD": "docker_image(name='test-image', image_tags=['1.0'])",
            "src/Dockerfile": "FROM python:3.8",
        }
    )
    target = rule_runner.get_target(Address("src", target_name="test-image"))
    result = run_docker(rule_runner, target)
    assert len(result.artifacts) == 1
    assert len(result.artifacts[0].extra_log_lines) == 2
    assert "Built docker image: test-image:1.0" == result.artifacts[0].extra_log_lines[0]
    assert "Docker image ID: sha256:" in result.artifacts[0].extra_log_lines[1]
