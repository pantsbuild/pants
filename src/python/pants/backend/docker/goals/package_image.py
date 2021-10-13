# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from os import path
from typing import cast

from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystems.docker_options import DockerEnvironmentVars, DockerOptions
from pants.backend.docker.target_types import (
    DockerImageSources,
    DockerImageTags,
    DockerImageVersion,
    DockerRegistriesField,
    DockerRepositoryField,
)
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerVersionContextError,
    DockerVersionContextValue,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.goals.run import RunFieldSet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)


class DockerRepositoryNameError(ValueError):
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
            ),
        )


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (DockerImageSources,)

    registries: DockerRegistriesField
    repository: DockerRepositoryField
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

    def image_refs(
        self,
        default_repository: str,
        registries: DockerRegistries,
        version_context: FrozenDict[str, DockerVersionContextValue],
    ) -> tuple[str, ...]:
        """The image refs are the full image name, including any registry and version tag.

        In the Docker world, the term `tag` is used both for what we here prefer to call the image
        `ref`, as well as for the image version, or tag, that is at the end of the image name
        separated with a colon. By introducing the image `ref` we can retain the use of `tag` for
        the version part of the image name.

        Returns all image refs to apply to the Docker image, on the form:

            [<registry>/]<repository-name>[:<tag>]

        Where the `<repository-name>` may have contain any number of separating slashes `/`,
        depending on the `default_repository` from configuration or the `repository` field
        on the target `docker_image`.

        This method will always return a non-empty tuple.
        """
        directory = path.basename(self.address.spec_path)
        parent_directory = path.basename(path.dirname(self.address.spec_path))
        repository_fmt = self.repository.value or default_repository
        try:
            repository = repository_fmt.format(
                name=self.address.target_name,
                directory=directory,
                parent_directory=parent_directory,
            )
        except KeyError as e:
            if self.repository.value:
                source = "`repository` field of the `docker_image` target " f"at {self.address}"
            else:
                source = "`[docker].default_repository` configuration option"

            raise DockerRepositoryNameError(
                f"Invalid value for the {source}: {repository_fmt!r}. Unknown key: {e}.\n\n"
                f"You may only reference any of `name`, `directory` or `parent_directory`."
            ) from e

        try:
            image_names = tuple(
                ":".join(s for s in [repository, tag] if s)
                for tag in [
                    cast(str, self.version.value).format(**version_context),
                    *(self.tags.value or []),
                ]
            )
        except (KeyError, ValueError) as e:
            msg = (
                "Invalid format string for the `version` field of the `docker_image` target at "
                f"{self.address}: {self.version.value!r}.\n\n"
            )
            if isinstance(e, KeyError):
                msg += f"The key {e} is unknown."
                if version_context:
                    msg += f' Try with one of: {", ".join(version_context.keys())}.'
                else:
                    msg += (
                        " There are currently no known keys to use. These keys can come from "
                        "`[docker].build_args` or parsed FROM instructions of your `Dockerfile`."
                    )
            else:
                msg += str(e)
            raise DockerVersionContextError(msg) from e

        registries_options = tuple(registries.get(*(self.registries.value or [])))
        if not registries_options:
            # The image name is also valid as image ref without registry.
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

    build_args_context = {
        build_arg_name: build_arg_value or env.vars[build_arg_name]
        for build_arg_name, _, build_arg_value in [
            build_arg.partition("=") for build_arg in options.build_args
        ]
    }

    version_context = context.version_context.merge({"build_args": build_args_context})

    tags = field_set.image_refs(
        default_repository=options.default_repository,
        registries=options.registries(),
        version_context=version_context,
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


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
        UnionRule(RunFieldSet, DockerFieldSet),
    ]
