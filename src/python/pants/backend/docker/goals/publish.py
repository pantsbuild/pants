# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain
from typing import cast

from pants.backend.docker.goals.package_image import BuiltDockerImage
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerRegistriesField, DockerSkipPushField
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.publish import (
    PublishFieldSet,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.process import InteractiveProcess
from pants.engine.rules import Get, collect_rules, rule

logger = logging.getLogger(__name__)


class PublishDockerImageRequest(PublishRequest):
    pass


@dataclass(frozen=True)
class PublishDockerImageFieldSet(PublishFieldSet):
    publish_request_type = PublishDockerImageRequest
    required_fields = (DockerRegistriesField,)

    registries: DockerRegistriesField
    skip_push: DockerSkipPushField

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData(
            {
                "publisher": "docker",
                "registries": self.registries.value or (),
                **super().get_output_data(),
            }
        )


@rule
async def push_docker_images(
    request: PublishDockerImageRequest, docker: DockerBinary, options: DockerOptions
) -> PublishProcesses:
    tags = tuple(
        chain.from_iterable(
            cast(BuiltDockerImage, image).tags
            for pkg in request.packages
            for image in pkg.artifacts
        )
    )

    if request.field_set.skip_push.value:
        return PublishProcesses(
            [
                PublishPackages(
                    names=tags,
                    description=f"(by `{request.field_set.skip_push.alias}` on {request.field_set.address})",
                ),
            ]
        )

    env = await Get(Environment, EnvironmentRequest(options.env_vars))
    processes = zip(tags, docker.push_image(tags, env))
    return PublishProcesses(
        [
            PublishPackages(
                names=(tag,),
                process=InteractiveProcess.from_process(process),
            )
            for tag, process in processes
        ]
    )


def rules():
    return (
        *collect_rules(),
        *PublishDockerImageFieldSet.rules(),
    )
