# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
)
from pants.backend.docker.utils import KeyValueSequenceUtil
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Target


class DockerBuildEnvironment(Environment):
    pass


@dataclass(frozen=True)
class DockerBuildEnvironmentRequest:
    target: Target


@rule
async def docker_build_environment_vars(
    request: DockerBuildEnvironmentRequest, docker_options: DockerOptions
) -> DockerBuildEnvironment:
    build_args = await Get(DockerBuildArgs, DockerBuildArgsRequest(request.target))
    env_vars = KeyValueSequenceUtil.from_strings(
        *{build_arg for build_arg in build_args if "=" not in build_arg},
        *docker_options.env_vars,
    )
    env = await Get(Environment, EnvironmentRequest(tuple(env_vars)))
    return DockerBuildEnvironment(env)


def rules():
    return collect_rules()
