# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha256

from pants.backend.docker.docker_binary import DockerBinary
from pants.engine.fs import Digest
from pants.engine.process import Process


def test_docker_binary_build_image():
    docker_path = "/bin/docker"
    dockerfile = "src/test/repo/Dockerfile"
    docker = DockerBinary(docker_path)
    digest = Digest(sha256().hexdigest(), 123)
    tag = "test:latest"
    build_request = docker.build_image(tag, digest, dockerfile)

    assert build_request == Process(
        argv=(docker_path, "build", "-t", tag, "-f", dockerfile, "."),
        input_digest=digest,
        description=f"Building docker image {tag}",
    )
