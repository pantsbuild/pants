# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from pants.backend.docker.goals.package_image import DockerPackageFieldSet
from pants.backend.docker.package_types import BuiltDockerImage
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import (
    DockerImageRegistriesField,
    DockerImageRunExtraArgsField,
    DockerImageSourceField,
)
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.package import PackageFieldSet, build_package
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.env_vars import environment_vars_subset
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.internals.graph import resolve_target
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import WrappedTargetRequest


@dataclass(frozen=True)
class DockerRunFieldSet(RunFieldSet):
    required_fields = (DockerImageSourceField,)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    extra_run_args: DockerImageRunExtraArgsField

    def get_run_args(self, options: DockerOptions) -> tuple[str, ...]:
        return tuple(options.run_args + (self.extra_run_args.value or ()))


@rule
async def docker_image_run_request(
    field_set: DockerRunFieldSet,
    docker: DockerBinary,
    options: DockerOptions,
    options_env_aware: DockerOptions.EnvironmentAware,
) -> RunRequest:
    wrapped_target = await resolve_target(
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
        **implicitly(),
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
    env, image = await concurrently(
        environment_vars_subset(EnvironmentVarsRequest(options_env_aware.env_vars), **implicitly()),
        build_package(**implicitly({build_request: PackageFieldSet})),
    )

    tag = cast(BuiltDockerImage, image.artifacts[0]).tags[0]
    run = docker.run_image(
        tag,
        docker_run_args=field_set.get_run_args(options),
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
