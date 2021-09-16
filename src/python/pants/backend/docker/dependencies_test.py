# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.docker.dependencies import InjectDockerDependencies, inject_docker_dependencies
from pants.backend.docker.parser import parse_dockerfile

# from pants.backend.docker.rules import rules
from pants.backend.docker.target_types import DockerDependencies, DockerImage
from pants.backend.python.target_types import PexBinary
from pants.engine.addresses import Address
from pants.engine.target import InjectedDependencies

# from pants.core.util_rules.source_files import rules as source_files_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            inject_docker_dependencies,
            parse_dockerfile,
            QueryRule(InjectedDependencies, (InjectDockerDependencies,)),
        ],
        target_types=[DockerImage, PexBinary],
    )


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
