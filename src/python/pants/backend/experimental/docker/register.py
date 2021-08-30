# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.rules import rules as docker_rules
from pants.backend.docker.tailor import rules as tailor_rules
from pants.backend.docker.target_types import DockerImage


def rules():
    return (
        *docker_rules(),
        *tailor_rules(),
    )


def target_types():
    return [
        DockerImage,
    ]
