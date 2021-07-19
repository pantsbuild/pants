# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha256
from os import path
from textwrap import dedent

from pants.backend.docker.rules import (
    DockerBinary,
    DockerDependencies,
    InjectDockerDependencies,
    inject_docker_dependencies,
)
from pants.backend.docker.target_types import DockerImage
from pants.backend.python.target_types import PexBinary
from pants.engine.addresses import Address
from pants.engine.fs import Digest
from pants.engine.process import Process
from pants.engine.target import InjectedDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_docker_build_image():
    source_path = "src/test/repo"
    docker_path = "/bin/docker"
    dockerfile = path.join(source_path, "Dockerfile")
    docker = DockerBinary(docker_path)
    digest = Digest(sha256().hexdigest(), 123)
    tag = "test:latest"
    build_request = docker.build_image(tag, digest, source_path, dockerfile)

    assert build_request == Process(
        argv=(docker_path, "build", "-t", tag, "-f", dockerfile, source_path),
        input_digest=digest,
        description=f"Building docker image {tag}",
    )


def test_inject_docker_dependencies() -> None:
    rule_runner = RuleRunner(
        rules=[
            inject_docker_dependencies,
            QueryRule(InjectedDependencies, [InjectDockerDependencies]),
        ],
        target_types=[DockerImage, PexBinary],
        objects={},
    )
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
