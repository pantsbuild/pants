# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.backend.docker.goals.package_image import BuiltDockerImage, DockerFieldSet
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunRequest
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule


@rule
async def docker_image_run_request(
    field_set: DockerFieldSet, docker: DockerBinary, options: DockerOptions
) -> RunRequest:
    env, image = await MultiGet(
        Get(Environment, EnvironmentRequest(options.env_vars)),
        Get(BuiltPackage, PackageFieldSet, field_set),
    )
    tag = cast(BuiltDockerImage, image.artifacts[0]).tags[0]
    run = docker.run_image(tag, docker_run_args=options.run_args, env=env)

    return RunRequest(args=run.argv, digest=image.digest, extra_env=run.env)


def rules():
    return collect_rules()
