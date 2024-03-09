# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.goals import package_image, publish, run_image
from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.util_rules import (
    dependencies,
    docker_binary,
    docker_build_args,
    docker_build_context,
    docker_build_env,
    dockerfile,
    mirror_images,
)


def rules():
    return [
        *dependencies.rules(),
        *docker_binary.rules(),
        *docker_build_args.rules(),
        *docker_build_context.rules(),
        *docker_build_env.rules(),
        *dockerfile.rules(),
        *dockerfile_parser.rules(),
        *mirror_images.rules(),
        *package_image.rules(),
        *publish.rules(),
        *run_image.rules(),
    ]
