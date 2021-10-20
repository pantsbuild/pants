# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.goals import generate_build_files
from pants.backend.docker.rules import rules as docker_rules
from pants.backend.docker.target_types import DockerImage
from pants.backend.python.util_rules import pex


def rules():
    return (
        *docker_rules(),
        *pex.rules(),
        *generate_build_files.rules(),
    )


def target_types():
    return [
        DockerImage,
    ]
