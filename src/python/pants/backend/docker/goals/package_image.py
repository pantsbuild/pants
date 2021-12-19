# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from os import path
from typing import Any, Iterator, Mapping

# Re-exporting BuiltDockerImage here, as it has its natural home here, but has moved out to resolve
# a dependency cycle from docker_build_context.
from pants.backend.docker.package_types import BuiltDockerImage as BuiltDockerImage
from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import (
    DockerBuildOptionFieldMixin,
    DockerImageSourceField,
    DockerImageTagsField,
    DockerRegistriesField,
    DockerRepositoryField,
)
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerVersionContext,
)
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunFieldSet
from pants.engine.addresses import Address
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target, WrappedTarget
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


class DockerImageTagValueError(ValueError):
    pass


class DockerRepositoryNameError(ValueError):
    pass


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (DockerImageSourceField,)

    registries: DockerRegistriesField
    repository: DockerRepositoryField
    source: DockerImageSourceField
    tags: DockerImageTagsField

    def format_tag(self, tag: str, version_context: DockerVersionContext) -> str:
        try:
            return tag.format(**version_context).lower()
        except (KeyError, ValueError) as e:
            msg = (
                "Invalid tag value for the `image_tags` field of the `docker_image` target at "
                f"{self.address}: {tag!r}.\n\n"
            )
            if isinstance(e, KeyError):
                msg += f"The placeholder {e} is unknown."
                if version_context:
                    msg += f' Try with one of: {", ".join(sorted(version_context.keys()))}.'
                else:
                    msg += (
                        " There are currently no known placeholders to use. These placeholders "
                        "can come from `[docker].build_args` or parsed FROM instructions of "
                        "your `Dockerfile`."
                    )
            else:
                msg += str(e)
            raise DockerImageTagValueError(msg) from e

    def format_repository(
        self, default_repository: str, repository_context: Mapping[str, Any]
    ) -> str:
        fmt_context = dict(
            directory=path.basename(self.address.spec_path),
            name=self.address.target_name,
            parent_directory=path.basename(path.dirname(self.address.spec_path)),
            **repository_context,
        )
        repository_fmt = self.repository.value or default_repository

        try:
            return repository_fmt.format(**fmt_context).lower()
        except (KeyError, ValueError) as e:
            if self.repository.value:
                source = f"`repository` field of the `docker_image` target at {self.address}"
            else:
                source = "`[docker].default_repository` configuration option"

            msg = f"Invalid value for the {source}: {repository_fmt!r}.\n\n"

            if isinstance(e, KeyError):
                msg += (
                    f"The placeholder {e} is unknown. "
                    f'Try with one of: {", ".join(sorted(fmt_context.keys()))}.'
                )
            else:
                msg += str(e)
            raise DockerRepositoryNameError(msg) from e

    def image_refs(
        self,
        default_repository: str,
        registries: DockerRegistries,
        version_context: DockerVersionContext,
    ) -> tuple[str, ...]:
        """The image refs are the full image name, including any registry and version tag.

        In the Docker world, the term `tag` is used both for what we here prefer to call the image
        `ref`, as well as for the image version, or tag, that is at the end of the image name
        separated with a colon. By introducing the image `ref` we can retain the use of `tag` for
        the version part of the image name.

        Returns all image refs to apply to the Docker image, on the form:

            [<registry>/]<repository-name>[:<tag>]

        Where the `<repository-name>` may contain any number of separating slashes `/`, depending on
        the `default_repository` from configuration or the `repository` field on the target
        `docker_image`.

        This method will always return a non-empty tuple.
        """
        repository_context = {}
        if "build_args" in version_context:
            repository_context["build_args"] = version_context["build_args"]

        repository = self.format_repository(default_repository, repository_context)
        image_names = tuple(
            ":".join(s for s in [repository, self.format_tag(tag, version_context)] if s)
            for tag in self.tags.value or ()
        )

        registries_options = tuple(registries.get(*(self.registries.value or [])))
        if not registries_options:
            # The image name is also valid as image ref without registry.
            return image_names

        return tuple(
            "/".join([registry.address, image_name])
            for image_name in image_names
            for registry in registries_options
        )


def get_build_options(target: Target) -> Iterator[str]:
    for field_type in target.field_types:
        if issubclass(field_type, DockerBuildOptionFieldMixin):
            yield from target[field_type].options()


@rule
async def build_docker_image(
    field_set: DockerFieldSet,
    options: DockerOptions,
    docker: DockerBinary,
) -> BuiltPackage:
    context, wrapped_target = await MultiGet(
        Get(
            DockerBuildContext,
            DockerBuildContextRequest(
                address=field_set.address,
                build_upstream_images=True,
            ),
        ),
        Get(WrappedTarget, Address, field_set.address),
    )

    tags = field_set.image_refs(
        default_repository=options.default_repository,
        registries=options.registries(),
        version_context=context.version_context,
    )

    result = await Get(
        ProcessResult,
        Process,
        docker.build_image(
            build_args=context.build_args,
            digest=context.digest,
            dockerfile=context.dockerfile,
            env=context.build_env.environment,
            tags=tags,
            extra_args=tuple(get_build_options(wrapped_target.target)),
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
