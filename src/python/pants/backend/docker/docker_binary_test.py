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
    tags = ["test:0.1.0", "test:latest"]
    build_request = docker.build_image(tags, digest, dockerfile)

    assert build_request == Process(
        argv=(docker_path, "build", "-t", tags[0], "-t", tags[1], "-f", dockerfile, "."),
        input_digest=digest,
        description="",
    )
    assert build_request.description == "Building docker image test:0.1.0 +1 additional tag."
