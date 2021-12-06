# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha256

import pytest

from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope


@pytest.fixture
def docker_path() -> str:
    return "/bin/docker"


@pytest.fixture
def docker(docker_path: str) -> DockerBinary:
    return DockerBinary(docker_path)


def test_docker_binary_build_image(docker_path: str, docker: DockerBinary) -> None:
    dockerfile = "src/test/repo/Dockerfile"
    digest = Digest(sha256().hexdigest(), 123)
    tags = (
        "test:0.1.0",
        "test:latest",
    )
    build_request = docker.build_image(tags, digest, dockerfile)

    assert build_request == Process(
        argv=(docker_path, "build", "-t", tags[0], "-t", tags[1], "-f", dockerfile, "."),
        input_digest=digest,
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert build_request.description == "Building docker image test:0.1.0 +1 additional tag."


def test_docker_binary_push_image(docker_path: str, docker: DockerBinary) -> None:
    assert docker.push_image(()) == ()

    image_ref = "registry/repo/name:tag"
    push_request = docker.push_image((image_ref,))
    assert push_request == (
        Process(
            argv=(docker_path, "push", image_ref),
            cache_scope=ProcessCacheScope.PER_SESSION,
            description="",  # The description field is marked `compare=False`
        ),
    )
    assert push_request[0].description == f"Pushing docker image {image_ref}"


def test_docker_binary_run_image(docker_path: str, docker: DockerBinary) -> None:
    image_ref = "registry/repo/name:tag"
    port_spec = "127.0.0.1:80:8080/tcp"
    run_request = docker.run_image(
        image_ref, docker_run_args=("-p", port_spec), image_args=("test-input",)
    )
    assert run_request == Process(
        argv=(docker_path, "run", "-p", port_spec, image_ref, "test-input"),
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert run_request.description == f"Running docker image {image_ref}"
