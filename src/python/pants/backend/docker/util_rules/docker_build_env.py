# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
)
from pants.backend.docker.utils import KeyValueSequenceUtil
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Target


class DockerBuildEnvironmentError(ValueError):
    @classmethod
    def from_key_error(cls, e: KeyError) -> DockerBuildEnvironmentError:
        return cls(
            f"The docker environment variable {e} is undefined. Either add a value for this "
            "variable to `[docker].env_vars`, or set a value in Pants's own environment."
        )


@dataclass(frozen=True)
class DockerBuildEnvironment:
    environment: Environment
    default_value: str | None = None

    @classmethod
    def create(
        cls, env: Mapping[str, str], default_value: str | None = None
    ) -> DockerBuildEnvironment:
        return cls(Environment(env), default_value)

    def __getitem__(self, key: str) -> str:
        if self.default_value is not None:
            return self.environment.get(key, self.default_value)
        try:
            return self.environment[key]
        except KeyError as e:
            raise DockerBuildEnvironmentError.from_key_error(e) from e


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
    return DockerBuildEnvironment.create(env)


def rules():
    return collect_rules()
