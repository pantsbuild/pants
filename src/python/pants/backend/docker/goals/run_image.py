# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, cast

from pants.backend.docker.goals.package_image import BuiltDockerImage, DockerFieldSet
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class DockerRunFieldSet(DockerFieldSet, RunFieldSet):
    def _image_refs_generator(self, *args, **kwargs) -> Iterator[str]:
        # We only care for one image tag when executing an image, and the first one will be a
        # `local_name` if there is one.
        for image_ref in super()._image_refs_generator(*args, **kwargs):
            yield image_ref
            return


@rule
async def docker_image_run_request(
    field_set: DockerRunFieldSet,
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
    field_set: DockerRunFieldSet,
) -> RunDebugAdapterRequest:
    raise NotImplementedError(
        "Debugging a Docker image using a debug adapter has not yet been implemented."
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(RunFieldSet, DockerRunFieldSet),
    ]
