# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

from pants.backend.docker.subsystems.docker_options import DockerOptions, UndefinedEnvVarBehavior
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
)
from pants.backend.docker.utils import KeyValueSequenceUtil
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Target

logger = logging.getLogger(__name__)


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
    undefined_env_var_behavior: UndefinedEnvVarBehavior

    @classmethod
    def create(
        cls,
        env: Mapping[str, str],
        undefined_env_var_behavior: UndefinedEnvVarBehavior = UndefinedEnvVarBehavior.RaiseError,
    ) -> DockerBuildEnvironment:
        return cls(Environment(env), undefined_env_var_behavior)

    def __getitem__(self, key: str) -> str:
        try:
            if self.undefined_env_var_behavior is UndefinedEnvVarBehavior.RaiseError:
                return self.environment[key]
            elif (
                self.undefined_env_var_behavior is UndefinedEnvVarBehavior.LogWarning
                and key not in self.environment
            ):
                logger.warning(
                    f"The Docker environment variable {key!r} is undefined. Provide a value for "
                    "it either in `[docker].env_vars` or in Pants's environment to silence this "
                    "warning."
                )
            return self.environment.get(key, "")
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
    return DockerBuildEnvironment.create(env, docker_options.undefined_env_var_behavior)


def rules():
    return collect_rules()
