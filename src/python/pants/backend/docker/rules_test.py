# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha256
from os import path

from pants.backend.docker.rules import DockerBinary
from pants.engine.fs import Digest
from pants.engine.process import Process


def test_docker_build_image():
    source_path = "src/test/repo"
    docker_path = "/bin/docker"
    dockerfile = path.join(source_path, "Dockerfile")
    docker = DockerBinary(docker_path)
    digest = Digest(sha256().hexdigest(), 123)
    build_request = docker.build_image(digest, source_path, dockerfile)

    assert build_request == Process(
        argv=(docker_path, "build", "-f", dockerfile, source_path),
        input_digest=digest,
        description=f"Building docker image from {dockerfile}",
    )
