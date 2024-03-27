# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from itertools import chain
from typing import DefaultDict, cast

from pants.backend.docker.goals.package_image import (
    BuiltDockerImage,
    DockerBuildSetup,
    DockerBuildSetupRequest,
    DockerPackageFieldSet,
)
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import (
    DockerImageBuildPlatformOptionField,
    DockerImageRegistriesField,
    DockerImageSkipPushField,
)
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.publish import (
    PublishFieldSet,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.engine.addresses import Addresses
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.process import InteractiveProcess
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Targets

logger = logging.getLogger(__name__)


class PublishDockerImageRequest(PublishRequest):
    pass


@dataclass(frozen=True)
class PublishDockerImageFieldSet(PublishFieldSet):
    publish_request_type = PublishDockerImageRequest
    required_fields = (DockerImageRegistriesField,)

    registries: DockerImageRegistriesField
    skip_push: DockerImageSkipPushField
    platforms: DockerImageBuildPlatformOptionField

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
    request: PublishDockerImageRequest,
    docker: DockerBinary,
    options: DockerOptions,
    options_env_aware: DockerOptions.EnvironmentAware,
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

    field_set = cast(PublishDockerImageFieldSet, request.field_set)
    if options.use_buildx and field_set.platforms.value:
        targets = await Get(Targets, Addresses([field_set.address]))
        target = targets.expect_single()

        build_setup = await Get(
            DockerBuildSetup,
            DockerBuildSetupRequest(
                field_set=DockerPackageFieldSet.create(target),
                ignore_platforms=False,
                push_image=True,
            ),
        )

        return PublishProcesses(
            [
                PublishPackages(
                    # TODO deal with tags that are intended to be skipped
                    names=tags,
                    process=InteractiveProcess.from_process(build_setup.process),
                )
            ]
        )

    env = await Get(EnvironmentVars, EnvironmentVarsRequest(options_env_aware.env_vars))
    skip_push_reasons: DefaultDict[str, DefaultDict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    jobs: list[PublishPackages] = []
    refs: list[str] = []
    processes: list[InteractiveProcess] = []

    for tag in tags:
        for registry in options.registries().registries.values():
            if registry.skip_push and tag.startswith(f"{registry.address}/"):
                skip_push_reasons["skip_push"][registry.alias].add(tag)
                break
            if registry.use_local_alias and tag.startswith(f"{registry.alias}/"):
                skip_push_reasons["use_local_alias"][registry.alias].add(tag)
                break
        else:
            refs.append(tag)
            processes.append(InteractiveProcess.from_process(docker.push_image(tag, env)))

    for ref, process in zip(refs, processes):
        jobs.append(
            PublishPackages(
                names=(ref,),
                process=process,
            )
        )

    for reason, skip_push in skip_push_reasons.items():
        for name, skip_tags in skip_push.items():
            jobs.append(
                PublishPackages(
                    names=tuple(skip_tags),
                    description=f"(by `{reason}` on registry @{name})",
                ),
            )

    return PublishProcesses(jobs)


def rules():
    return (
        *collect_rules(),
        *PublishDockerImageFieldSet.rules(),
    )
