# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from pants.backend.docker.goals.package_image import BuiltDockerImage, DockerPackageFieldSet
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import (
    DockerImageRegistriesField,
    DockerImageRunExtraArgsField,
    DockerImageSourceField,
)
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import WrappedTarget, WrappedTargetRequest


@dataclass(frozen=True)
class DockerRunFieldSet(RunFieldSet):
    required_fields = (DockerImageSourceField,)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC


@rule
async def docker_image_run_request(
    field_set: DockerRunFieldSet,
    docker: DockerBinary,
    options: DockerOptions,
    options_env_aware: DockerOptions.EnvironmentAware,
) -> RunRequest:
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
    )
    build_request = DockerPackageFieldSet.create(wrapped_target.target)
    registries = options.registries()
    for registry in registries.get(*(build_request.registries.value or [])):
        if registry.use_local_alias:
            # We only need to tag a single image name for run requests if there is a registry with
            # `use_local_alias` as true.
            build_request = replace(
                build_request,
                registries=DockerImageRegistriesField((registry.alias,), field_set.address),
            )
            break
    env, image = await MultiGet(
        Get(EnvironmentVars, EnvironmentVarsRequest(options_env_aware.env_vars)),
        Get(BuiltPackage, PackageFieldSet, build_request),
    )

    docker_run_args = options.run_args + (
        wrapped_target.target.get(DockerImageRunExtraArgsField).value or ()
    )
    tag = cast(BuiltDockerImage, image.artifacts[0]).tags[0]
    run = docker.run_image(
        tag,
        docker_run_args=docker_run_args,
        env=env,
    )

    return RunRequest(
        digest=image.digest,
        args=run.argv,
        extra_env=run.env,
        immutable_input_digests=run.immutable_input_digests,
    )


def rules():
    return [
        *collect_rules(),
        *DockerRunFieldSet.rules(),
    ]
