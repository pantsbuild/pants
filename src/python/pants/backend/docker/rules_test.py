# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha256
from os import path
from textwrap import dedent

import pytest

from pants.backend.docker.rules import (
    DockerBinary,
    DockerBinaryRequest,
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerFieldSet,
    InjectDockerDependencies,
    build_docker_image,
    inject_docker_dependencies,
    parse_dockerfile,
)
from pants.backend.docker.target_types import DockerDependencies, DockerImage
from pants.backend.python.target_types import PexBinary
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST, EMPTY_SNAPSHOT, Digest, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.target import InjectedDependencies, TransitiveTargets, TransitiveTargetsRequest
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.ordered_set import FrozenOrderedSet


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
            parse_dockerfile,
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


@pytest.mark.parametrize(
    "target_values, expected_features",
    [
        (
            dict(),
            dict(
                context_root="docker/test/.",
            ),
        ),
        (
            dict(
                version="1.2.3",
            ),
            dict(
                version="1.2.3",
            ),
        ),
        (
            dict(
                build_root="/",
            ),
            dict(
                context_root=".",
            ),
        ),
        (
            dict(
                build_root="foo/bar",
            ),
            dict(
                context_root="docker/test/foo/bar",
            ),
        ),
        (
            dict(
                build_root="/foo/bar",
            ),
            dict(
                context_root="foo/bar",
            ),
        ),
    ],
)
def test_build_docker_image(target_values, expected_features):
    address = Address("docker/test", target_name="image")
    image = DockerImage(
        address=address,
        unhydrated_values=target_values,
    )
    targets = {address: TransitiveTargets(roots=(image,), dependencies=FrozenOrderedSet())}
    field_set = DockerFieldSet.create(image)

    def build_context_mock(request: DockerBuildContextRequest) -> DockerBuildContext:
        if "context_root" in expected_features:
            assert expected_features["context_root"] == request.context_root

        return DockerBuildContext(digest=EMPTY_DIGEST)

    result = run_rule_with_mocks(
        build_docker_image,
        rule_args=[field_set],
        mock_gets=[
            MockGet(
                output_type=DockerBinary,
                input_type=DockerBinaryRequest,
                mock=lambda _: DockerBinary("/dummy/docker"),
            ),
            MockGet(
                output_type=TransitiveTargets,
                input_type=TransitiveTargetsRequest,
                mock=lambda request: targets[request.roots[0]],
            ),
            MockGet(
                output_type=DockerBuildContext,
                input_type=DockerBuildContextRequest,
                mock=build_context_mock,
            ),
            MockGet(
                output_type=Snapshot,
                input_type=Digest,
                mock=lambda _: EMPTY_SNAPSHOT,
            ),
            MockGet(
                output_type=ProcessResult,
                input_type=Process,
                # Process() generation has its own tests in test_docker_build_image
                mock=lambda _: ProcessResult(
                    stdout=b"stdout",
                    stdout_digest=EMPTY_FILE_DIGEST,
                    stderr=b"stderr",
                    stderr_digest=EMPTY_FILE_DIGEST,
                    output_digest=EMPTY_DIGEST,
                ),
            ),
        ],
        # union_membership=
    )

    assert result.digest == EMPTY_DIGEST
    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath is None

    version = expected_features.get("version", "latest")
    assert f"Built docker image: image:{version}" in result.artifacts[0].extra_log_lines
