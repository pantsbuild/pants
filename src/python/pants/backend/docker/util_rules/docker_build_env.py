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
            f"The Docker environment variable {e} is undefined. You may provide a value for "
            "this variable either in `[docker].env_vars` or in Pants's own environment."
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
        return self.get(key)

    def get(self, key: str, default: str | None = None) -> str:
        if default is not None:
            return self.environment.get(key, default)
        try:
            return self.environment[key]
        except KeyError as e:
            if self.undefined_env_var_behavior is UndefinedEnvVarBehavior.Ignore:
                return ""

            err = DockerBuildEnvironmentError.from_key_error(e)
            if self.undefined_env_var_behavior is UndefinedEnvVarBehavior.LogWarning:
                logger.warning(str(err))
                return ""

            assert self.undefined_env_var_behavior is UndefinedEnvVarBehavior.RaiseError
            raise err from e


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
