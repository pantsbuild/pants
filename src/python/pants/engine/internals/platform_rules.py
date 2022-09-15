# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.environments import (
    DockerImageField,
    DockerPlatformField,
    EnvironmentTarget,
)
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.session import SessionValues
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


@rule
def current_platform(env_tgt: EnvironmentTarget) -> Platform:
    if env_tgt.val is None or not env_tgt.val.has_field(DockerPlatformField):
        return Platform.create_for_localhost()
    return Platform(env_tgt.val[DockerPlatformField].normalized_value)


@rule
async def complete_environment_vars(
    session_values: SessionValues, env_tgt: EnvironmentTarget
) -> CompleteEnvironmentVars:
    if not env_tgt.val or not env_tgt.val.has_field(DockerImageField):
        return session_values[CompleteEnvironmentVars]
    env_process_result = await Get(
        ProcessResult,
        Process(
            ["env", "-0"],
            description=softwrap(
                f"""
                Extract environment variables from the Docker image
                {env_tgt.val[DockerImageField].value}
                """
            ),
            level=LogLevel.DEBUG,
        ),
    )
    result = {}
    for line in env_process_result.stdout.decode("utf-8").rstrip().split("\0"):
        if not line:
            continue
        k, v = line.split("=", maxsplit=1)
        result[k] = v
    return CompleteEnvironmentVars(result)


@rule
def environment_vars_subset(
    complete_env_vars: CompleteEnvironmentVars, request: EnvironmentVarsRequest
) -> EnvironmentVars:
    return EnvironmentVars(
        complete_env_vars.get_subset(
            requested=tuple(request.requested),
            allowed=(None if request.allowed is None else tuple(request.allowed)),
        ).items()
    )


def rules():
    return collect_rules()
