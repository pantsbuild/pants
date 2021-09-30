# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from pants.backend.docker.docker_binary import DockerBinary, DockerBinaryRequest
from pants.backend.docker.docker_build_context import DockerBuildContext, DockerBuildContextRequest
from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystem import DockerOptions
from pants.backend.docker.target_types import (
    DockerImageSources,
    DockerImageVersion,
    DockerRegistriesField,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet):
    required_fields = (DockerImageSources,)

    image_version: DockerImageVersion
    registries: DockerRegistriesField
    sources: DockerImageSources

    @property
    def dockerfile_relpath(self) -> str:
        # DockerImageSources.expected_num_files==1 ensures this is non-empty
        assert self.sources.value
        return self.sources.value[0]

    @property
    def dockerfile_path(self) -> str:
        return os.path.join(self.address.spec_path, self.dockerfile_relpath)

    @property
    def image_name(self) -> str:
        return ":".join(s for s in [self.address.target_name, self.image_version.value] if s)

    def image_tags(self, registries: DockerRegistries) -> tuple[str, ...]:
        image_name = self.image_name
        registries_options = tuple(registries.get(*(self.registries.value or [])))
        if not registries_options:
            return (image_name,)

        return tuple("/".join([registry.address, image_name]) for registry in registries_options)


@rule
async def build_docker_image(
    field_set: DockerFieldSet,
    options: DockerOptions,
) -> BuiltPackage:
    docker, context = await MultiGet(
        Get(DockerBinary, DockerBinaryRequest()),
        Get(
            DockerBuildContext,
            DockerBuildContextRequest(
                address=field_set.address,
                build_upstream_images=True,
            ),
        ),
    )

    image_tags = field_set.image_tags(options.registries())
    result = await Get(
        ProcessResult,
        Process,
        docker.build_image(
            tags=image_tags,
            digest=context.digest,
            dockerfile=field_set.dockerfile_path,
        ),
    )

    logger.debug(
        f"Docker build output for {image_tags[0]}:\n"
        f"{result.stdout.decode()}\n"
        f"{result.stderr.decode()}"
    )

    image_tags_string = image_tags[0] if len(image_tags) == 1 else (f"\n{bullet_list(image_tags)}")

    return BuiltPackage(
        result.output_digest,
        (
            BuiltPackageArtifact(
                relpath=None,
                extra_log_lines=(
                    f"Built docker image: {image_tags_string}",
                    "To try out the image interactively:",
                    f"    docker run -it --rm {image_tags[0]} [entrypoint args...]",
                    "To push your image:",
                    f"    docker push {image_tags[0]}",
                    "",
                ),
            ),
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
    ]
