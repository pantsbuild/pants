# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.target_types import DockerDependencies, DockerImage
from pants.backend.docker.util_rules.dependencies import (
    InjectDockerDependencies,
    inject_docker_dependencies,
)
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.engine.addresses import Address
from pants.engine.target import InjectedDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *parser_rules(),
            *pex_rules(),
            inject_docker_dependencies,
            QueryRule(InjectedDependencies, (InjectDockerDependencies,)),
        ],
        target_types=[DockerImage, PexBinary],
    )
    rule_runner.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def test_inject_docker_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "project/image/test",
        dedent(
            """\
            docker_image(name="image")
            """
        ),
    )
    rule_runner.create_file(
        "project/image/test/Dockerfile",
        dedent(
            """\
            FROM baseimage
            ENTRYPOINT ["./entrypoint"]
            COPY project.hello.main/main_binary.pex /entrypoint
            """
        ),
    )
    rule_runner.add_to_build_file(
        "project/hello/main",
        dedent(
            """\
            pex_binary(name="main_binary")
            """
        ),
    )
    tgt = rule_runner.get_target(Address("project/image/test", target_name="image"))
    injected = rule_runner.request(
        InjectedDependencies,
        [InjectDockerDependencies(tgt[DockerDependencies])],
    )
    assert injected == InjectedDependencies(
        [Address("project/hello/main", target_name="main_binary")]
    )
