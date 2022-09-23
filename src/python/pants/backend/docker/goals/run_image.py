# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.backend.docker.goals.package_image import BuiltDockerImage, DockerFieldSet
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunDebugAdapterRequest, RunRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule


@rule
async def docker_image_run_request(
    field_set: DockerFieldSet,
    docker: DockerBinary,
    options: DockerOptions,
    options_env_aware: DockerOptions.EnvironmentAware,
) -> RunRequest:
    env, image = await MultiGet(
        Get(EnvironmentVars, EnvironmentVarsRequest(options_env_aware.env_vars)),
        Get(BuiltPackage, PackageFieldSet, field_set),
    )
    tag = cast(BuiltDockerImage, image.artifacts[0]).tags[0]
    run = docker.run_image(tag, docker_run_args=options.run_args, env=env)

    return RunRequest(
        digest=image.digest,
        args=run.argv,
        extra_env=run.env,
        immutable_input_digests=run.immutable_input_digests,
    )


@rule
async def docker_image_run_debug_adapter_request(
    field_set: DockerFieldSet,
) -> RunDebugAdapterRequest:
    raise NotImplementedError(
        "Debugging a Docker image using a debug adapter has not yet been implemented."
    )


def rules():
    return collect_rules()
