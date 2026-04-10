# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from itertools import chain
from typing import DefaultDict, cast

from pants.backend.docker.goals.package_image import (
    DockerPackageFieldSet,
    GetImageRefsRequest,
    get_docker_image_build_process,
    get_image_refs,
)
from pants.backend.docker.package_types import BuiltDockerImage
from pants.backend.docker.registries import DockerRegistryOptions
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageRegistriesField, DockerImageSkipPushField
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.package import PackageFieldSet
from pants.core.goals.publish import (
    CheckSkipRequest,
    CheckSkipResult,
    PublishFieldSet,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.core.util_rules.env_vars import environment_vars_subset
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.process import InteractiveProcess, Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


class PublishDockerImageRequest(PublishRequest):
    pass


@dataclass(frozen=True)
class PublishDockerImageFieldSet(PublishFieldSet, DockerPackageFieldSet):
    publish_request_type = PublishDockerImageRequest
    required_fields = (  # type: ignore[assignment]
        *DockerPackageFieldSet.required_fields,
        DockerImageRegistriesField,
    )

    skip_push: DockerImageSkipPushField

    def make_skip_request(
        self, package_fs: PackageFieldSet
    ) -> PublishDockerImageSkipRequest | None:
        return (
            PublishDockerImageSkipRequest(publish_fs=self, package_fs=package_fs)
            if isinstance(package_fs, DockerPackageFieldSet)
            else None
        )

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData(
            {
                "publisher": "docker",
                "registries": self.registries.value or (),
                **super().get_output_data(),
            }
        )


class PublishDockerImageSkipRequest(CheckSkipRequest[PublishDockerImageFieldSet]):
    package_fs: DockerPackageFieldSet


@rule
async def check_if_skip_push(
    request: PublishDockerImageSkipRequest, options: DockerOptions
) -> CheckSkipResult:
    skip_registries = {
        registry for registry in options.registries().registries.values() if registry.skip_push
    }
    if skip_registries or request.publish_fs.skip_push.value:
        image_refs = await get_image_refs(
            GetImageRefsRequest(field_set=request.package_fs, build_upstream_images=False),
            **implicitly(),
        )
        if request.publish_fs.skip_push.value:
            return CheckSkipResult.skip(
                names=[tag.full_name for registry in image_refs for tag in registry.tags],
                description=f"(by `{request.publish_fs.skip_push.alias}` on {request.address})",
                data=request.publish_fs.get_output_data(),
            )
        if all(image_ref.registry in skip_registries for image_ref in image_refs):
            output_data = request.publish_fs.get_output_data()
            return CheckSkipResult(
                PublishPackages(
                    names=tuple(tag.full_name for tag in image_ref.tags),
                    description=f"(by skip_push on @{cast(DockerRegistryOptions, image_ref.registry).alias})",
                    data=output_data,
                )
                for image_ref in image_refs
            )
    return (
        CheckSkipResult.skip(skip_packaging_only=True)
        if request.package_fs.pushes_on_package()
        else CheckSkipResult.no_skip()
    )


@rule
async def push_docker_images(
    request: PublishDockerImageRequest,
    docker: DockerBinary,
    options: DockerOptions,
    options_env_aware: DockerOptions.EnvironmentAware,
) -> PublishProcesses:
    if cast(DockerPackageFieldSet, request.field_set).pushes_on_package():
        build_process = await get_docker_image_build_process(request.field_set, **implicitly())
        return PublishProcesses(
            [
                PublishPackages(
                    names=build_process.tags,
                    process=build_process.process
                    if options.publish_noninteractively
                    else InteractiveProcess.from_process(build_process.process),
                )
            ]
        )

    tags = tuple(
        chain.from_iterable(
            cast(BuiltDockerImage, image).tags
            for pkg in request.packages
            for image in pkg.artifacts
        )
    )

    env = await environment_vars_subset(
        EnvironmentVarsRequest(options_env_aware.env_vars), **implicitly()
    )
    skip_push_reasons: DefaultDict[str, DefaultDict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    jobs: list[PublishPackages] = []
    refs: list[str] = []
    processes: list[Process | InteractiveProcess] = []

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
            push_process = docker.push_image(tag, env)
            if options.publish_noninteractively:
                processes.append(push_process)
            else:
                processes.append(InteractiveProcess.from_process(push_process))

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
        UnionRule(CheckSkipRequest, PublishDockerImageSkipRequest),
    )
