# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from os import path

from pants.backend.docker.docker_binary import DockerBinary, DockerBinaryRequest
from pants.backend.docker.docker_build_context import DockerBuildContext, DockerBuildContextRequest
from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystem import DockerOptions
from pants.backend.docker.target_types import (
    DockerImageName,
    DockerImageNameTemplate,
    DockerImageSources,
    DockerImageTags,
    DockerImageVersion,
    DockerRegistriesField,
    DockerRepository,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet):
    required_fields = (DockerImageSources,)

    name: DockerImageName
    name_template: DockerImageNameTemplate
    registries: DockerRegistriesField
    repository: DockerRepository
    sources: DockerImageSources
    tags: DockerImageTags
    version: DockerImageVersion

    @property
    def dockerfile_relpath(self) -> str:
        # DockerImageSources.expected_num_files==1 ensures this is non-empty
        assert self.sources.value
        return self.sources.value[0]

    @property
    def dockerfile_path(self) -> str:
        return path.join(self.address.spec_path, self.dockerfile_relpath)

    def image_names(
        self, default_name_template: str, registries: DockerRegistries
    ) -> tuple[str, ...]:
        """This method will always return a non-empty tuple."""
        default_parent = path.basename(path.dirname(self.address.spec_path))
        default_repo = path.basename(self.address.spec_path)
        repo = self.repository.value or default_repo
        name_template = self.name_template.value or default_name_template
        image_name = name_template.format(
            name=self.name.value or self.address.target_name,
            repository=repo,
            sub_repository="/".join(
                [default_repo if self.repository.value else default_parent, repo]
            ),
        )
        image_names = tuple(
            ":".join(s for s in [image_name, tag] if s)
            for tag in [self.version.value, *(self.tags.value or [])]
        )

        registries_options = tuple(registries.get(*(self.registries.value or [])))
        if not registries_options:
            return image_names

        return tuple(
            "/".join([registry.address, image_name])
            for image_name in image_names
            for registry in registries_options
        )


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

    tags = field_set.image_names(options.default_image_name_template, options.registries())
    result = await Get(
        ProcessResult,
        Process,
        docker.build_image(
            tags=tags,
            digest=context.digest,
            dockerfile=field_set.dockerfile_path,
        ),
    )

    logger.debug(
        f"Docker build output for {tags[0]}:\n"
        f"{result.stdout.decode()}\n"
        f"{result.stderr.decode()}"
    )

    tags_string = tags[0] if len(tags) == 1 else (f"\n{bullet_list(tags)}")

    return BuiltPackage(
        result.output_digest,
        (
            BuiltPackageArtifact(
                relpath=None,
                extra_log_lines=(
                    f"Built docker {pluralize(len(tags), 'image', False)}: {tags_string}",
                    "To try out the image interactively:",
                    f"    docker run -it --rm {tags[0]} [entrypoint args...]",
                    "To push your image:",
                    f"    docker push {tags[0]}",
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
