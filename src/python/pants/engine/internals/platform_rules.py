# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.environments import (
    DockerImageField,
    DockerPlatformField,
    EnvironmentsSubsystem,
    EnvironmentTarget,
    RemotePlatformField,
)
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.session import SessionValues
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel


@rule
def current_platform(
    env_tgt: EnvironmentTarget,
    global_options: GlobalOptions,
    environments_subsystem: EnvironmentsSubsystem,
) -> Platform:
    if env_tgt.val:
        if env_tgt.val.has_field(DockerPlatformField):
            return Platform(env_tgt.val[DockerPlatformField].normalized_value)
        if env_tgt.val.has_field(RemotePlatformField):
            return Platform(env_tgt.val[RemotePlatformField].value)
        # Else, it's a local environment.
        return Platform.create_for_localhost()

    # If the environments mechanism is not used, fall back to legacy behavior of
    # `--remote-execution` being a global toggle.
    if not environments_subsystem.names and global_options.remote_execution:
        return Platform.linux_x86_64

    return Platform.create_for_localhost()


@rule
async def complete_environment_vars(
    session_values: SessionValues,
    env_tgt: EnvironmentTarget,
    global_options: GlobalOptions,
    environments_subsystem: EnvironmentsSubsystem,
) -> CompleteEnvironmentVars:
    # If a local environment is used, we simply use SessionValues. Otherwise, we need to run `env`
    # and parse the output.
    #
    # Note that running `env` works for both Docker and Remote Execution because we intentionally
    # do not strip the environment from either runtime. It is reasonable to not strip because
    # every user will have the same consistent Docker image or Remote Execution environment, unlike
    # local environments.
    if env_tgt.val:
        if env_tgt.val.has_field(DockerImageField):
            description_of_env_source = f"the Docker image {env_tgt.val[DockerImageField].value}"
        elif env_tgt.val.has_field(RemotePlatformField):
            description_of_env_source = "the remote execution environment"
        else:
            # Else, it's a local environment.
            return session_values[CompleteEnvironmentVars]
    else:
        # If the environments mechanism is not used, fall back to legacy behavior of
        # `--remote-execution` being a global toggle.
        if not environments_subsystem.names and global_options.remote_execution:
            description_of_env_source = "the remote execution environment"
        else:
            return session_values[CompleteEnvironmentVars]

    env_process_result = await Get(
        ProcessResult,
        Process(
            ["env", "-0"],
            description=f"Extract environment variables from {description_of_env_source}",
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
