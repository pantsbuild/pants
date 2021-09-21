# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from textwrap import dedent

import pytest

from pants.backend.docker.dependencies import InjectDockerDependencies, inject_docker_dependencies
from pants.backend.docker.parser import DockerfileParser, parse_dockerfile
from pants.backend.docker.target_types import DockerDependencies, DockerImage
from pants.backend.python.target_types import PexBinary
from pants.engine.addresses import Address
from pants.engine.target import InjectedDependencies
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


@pytest.mark.parametrize(
    "copy_source, putative_target_address",
    [
        ("a/b", None),
        ("a/b.c", None),
        ("a.b", None),
        ("a.pex", ":a"),
        ("a/b.pex", "a:b"),
        ("a.b/c.pex", "a/b:c"),
        ("a.b.c/d.pex", "a/b/c:d"),
        ("a.b/c/d.pex", None),
        ("a/b/c.pex", None),
        ("a.0-1/b_2.pex", "a/0-1:b_2"),
        ("a#b/c.pex", None),
    ],
)
def test_translate_to_address(copy_source, putative_target_address) -> None:
    pex_target_regexp = re.compile(DockerfileParser.pex_target_regexp, re.VERBOSE)
    actual = DockerfileParser.translate_to_address(copy_source, pex_target_regexp)
    assert actual == putative_target_address
