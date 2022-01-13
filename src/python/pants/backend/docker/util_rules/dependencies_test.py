# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.docker.goals import package_image
from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.target_types import DockerImageDependenciesField, DockerImageTarget
from pants.backend.docker.util_rules import dockerfile
from pants.backend.docker.util_rules.dependencies import (
    InjectDockerDependencies,
    inject_docker_dependencies,
)
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules import pex
from pants.engine.addresses import Address
from pants.engine.target import InjectedDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *dockerfile.rules(),
            *dockerfile_parser.rules(),
            *package_image.rules(),
            *package_pex_binary.rules(),
            *pex.rules(),
            inject_docker_dependencies,
            QueryRule(InjectedDependencies, (InjectDockerDependencies,)),
        ],
        target_types=[DockerImageTarget, PexBinary],
    )
    rule_runner.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def test_inject_docker_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/image/test/BUILD": dedent(
                """\
                docker_image(name="base")
                docker_image(name="image")
                """
            ),
            "project/image/test/Dockerfile": dedent(
                """\
                ARG BASE_IMAGE=:base
                FROM $BASE_IMAGE
                ENTRYPOINT ["./entrypoint"]
                COPY project.hello.main/main_binary.pex /entrypoint
                """
            ),
            "project/hello/main/BUILD": dedent(
                """\
                pex_binary(name="main_binary")
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("project/image/test", target_name="image"))
    injected = rule_runner.request(
        InjectedDependencies,
        [InjectDockerDependencies(tgt[DockerImageDependenciesField])],
    )
    assert injected == InjectedDependencies(
        [
            Address("project/hello/main", target_name="main_binary"),
            Address("project/image/test", target_name="base"),
        ]
    )
