# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from os import path
from typing import cast

from pants.backend.docker.docker_binary import DockerBinary
from pants.backend.docker.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerVersionContextError,
    DockerVersionContextValue,
)
from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystem import DockerEnvironmentVars, DockerOptions
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
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)


class DockerNameTemplateError(ValueError):
    pass


@dataclass(frozen=True)
class BuiltDockerImage(BuiltPackageArtifact):
    tags: tuple[str, ...] = ()

    @classmethod
    def create(cls, tags: tuple[str, ...]) -> BuiltDockerImage:
        tags_string = tags[0] if len(tags) == 1 else (f"\n{bullet_list(tags)}")
        return cls(
            tags=tags,
            relpath=None,
            extra_log_lines=(
                f"Built docker {pluralize(len(tags), 'image', False)}: {tags_string}",
                "To try out the image interactively:",
                f"    docker run -it --rm {tags[0]} [entrypoint args...]",
            ),
        )


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet, RunFieldSet):
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
        self,
        default_name_template: str,
        registries: DockerRegistries,
        version_context: FrozenDict[str, DockerVersionContextValue],
    ) -> tuple[str, ...]:
        """This method will always return a non-empty tuple."""
        default_parent = path.basename(path.dirname(self.address.spec_path))
        default_repo = path.basename(self.address.spec_path)
        repo = self.repository.value or default_repo
        name_template = self.name_template.value or default_name_template
        try:
            image_name = name_template.format(
                name=self.name.value or self.address.target_name,
                repository=repo,
                sub_repository="/".join(
                    [default_repo if self.repository.value else default_parent, repo]
                ),
            )
        except KeyError as e:
            if self.name_template.value:
                source = (
                    "from the `image_name_template` field of the docker_image target "
                    f"at {self.address}"
                )
            else:
                source = "from the [docker].default_image_name_template configuration option"

            raise DockerNameTemplateError(
                f"Invalid image name template {source}: {name_template!r}. Unknown key: {e}.\n\n"
                f"Use any of 'name', 'repository' or 'sub_repository' in the template string."
            ) from e

        try:
            image_names = tuple(
                ":".join(s for s in [image_name, tag] if s)
                for tag in [
                    cast(str, self.version.value).format(**version_context),
                    *(self.tags.value or []),
                ]
            )
        except (KeyError, ValueError) as e:
            msg = (
                "Invalid format string for the `version` field of the docker_image target at "
                f"{self.address}: {self.version.value!r}.\n\n"
            )
            if isinstance(e, KeyError):
                msg += (
                    f"The key {e} is unknown. Try with one of: "
                    f'{", ".join(version_context.keys())}.'
                )
            else:
                msg += str(e)
            raise DockerVersionContextError(msg) from e

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
    docker: DockerBinary,
    env: DockerEnvironmentVars,
) -> BuiltPackage:
    context = await Get(
        DockerBuildContext,
        DockerBuildContextRequest(
            address=field_set.address,
            build_upstream_images=True,
        ),
    )

    tags = field_set.image_names(
        default_name_template=options.default_image_name_template,
        registries=options.registries(),
        version_context=context.version_context,
    )

    result = await Get(
        ProcessResult,
        Process,
        docker.build_image(
            build_args=options.build_args,
            digest=context.digest,
            dockerfile=field_set.dockerfile_path,
            env=env.vars,
            tags=tags,
        ),
    )

    logger.debug(
        f"Docker build output for {tags[0]}:\n"
        f"{result.stdout.decode()}\n"
        f"{result.stderr.decode()}"
    )

    return BuiltPackage(
        result.output_digest,
        (BuiltDockerImage.create(tags),),
    )


@rule
async def docker_image_run_request(field_set: DockerFieldSet, docker: DockerBinary) -> RunRequest:
    image = await Get(BuiltPackage, PackageFieldSet, field_set)
    return RunRequest(
        digest=image.digest,
        args=(
            docker.path,
            "run",
            "-it",
            "--rm",
            cast(BuiltDockerImage, image.artifacts[0]).tags[0],
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
        UnionRule(RunFieldSet, DockerFieldSet),
    ]
