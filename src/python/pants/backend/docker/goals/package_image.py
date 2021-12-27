# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from os import path
from textwrap import dedent
from typing import Any, Iterator, Mapping

from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import (
    DockerBuildOptionFieldMixin,
    DockerImageSourceField,
    DockerImageTagsField,
    DockerImageTargetStageField,
    DockerRegistriesField,
    DockerRepositoryField,
)
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerVersionContext,
)
from pants.backend.docker.utils import format_rename_suggestion
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.goals.run import RunFieldSet
from pants.engine.addresses import Address
from pants.engine.process import FallibleProcessResult, Process, ProcessExecutionFailure
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target, WrappedTarget
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions, ProcessCleanupOption
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)


class DockerImageTagValueError(ValueError):
    pass


class DockerRepositoryNameError(ValueError):
    pass


class DockerBuildTargetStageError(ValueError):
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
    required_fields = (DockerImageSourceField,)

    registries: DockerRegistriesField
    repository: DockerRepositoryField
    tags: DockerImageTagsField
    target_stage: DockerImageTargetStageField

    def format_tag(self, tag: str, version_context: DockerVersionContext) -> str:
        try:
            return tag.format(**version_context)
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
            return repository_fmt.format(**fmt_context)
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


def get_build_options(
    context: DockerBuildContext,
    field_set: DockerFieldSet,
    global_target_stage_option: str | None,
    target: Target,
) -> Iterator[str]:
    # Build options from target fields inheriting from DockerBuildOptionFieldMixin
    for field_type in target.field_types:
        if issubclass(field_type, DockerBuildOptionFieldMixin):
            yield from target[field_type].options()

    # Target stage
    target_stage = None
    if global_target_stage_option in context.stages:
        target_stage = global_target_stage_option
    elif field_set.target_stage.value:
        target_stage = field_set.target_stage.value
        if target_stage not in context.stages:
            raise DockerBuildTargetStageError(
                f"The {field_set.target_stage.alias!r} field in `{target.alias}` "
                f"{field_set.address} was set to {target_stage!r}"
                + (
                    f", but there is no such stage in `{context.dockerfile}`. "
                    f"Available stages: {', '.join(context.stages)}."
                    if context.stages
                    else f", but there are no named stages in `{context.dockerfile}`."
                )
            )

    if target_stage:
        yield from ("--target", target_stage)


@rule
async def build_docker_image(
    field_set: DockerFieldSet,
    options: DockerOptions,
    global_options: GlobalOptions,
    docker: DockerBinary,
    process_cleanup: ProcessCleanupOption,
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

    process = docker.build_image(
        build_args=context.build_args,
        digest=context.digest,
        dockerfile=context.dockerfile,
        env=context.build_env.environment,
        tags=tags,
        extra_args=tuple(
            get_build_options(
                context=context,
                field_set=field_set,
                global_target_stage_option=options.build_target_stage,
                target=wrapped_target.target,
            )
        ),
    )
    result = await Get(FallibleProcessResult, Process, process)

    if result.exit_code != 0:
        maybe_msg = docker_build_failed(
            field_set.address,
            context,
            global_options.options.colors,
        )
        if maybe_msg:
            logger.warning(maybe_msg)

        raise ProcessExecutionFailure(
            result.exit_code,
            result.stdout,
            result.stderr,
            process.description,
            process_cleanup=process_cleanup.val,
        )

    logger.debug(
        dedent(
            f"""\
            Docker build output for {tags[0]}:
            stdout:
            {result.stdout.decode()}

            stderr:
            {result.stderr.decode()}
            """
        )
    )

    return BuiltPackage(
        result.output_digest,
        (BuiltDockerImage.create(tags),),
    )


def docker_build_failed(address: Address, context: DockerBuildContext, colors: bool) -> str | None:
    if not context.copy_source_vs_context_source:
        return None

    msg = (
        f"Docker build failed for `docker_image` {address}. The {context.dockerfile} have `COPY` "
        "instructions where the source files may not have been found in the Docker build context."
        "\n\n"
    )

    renames = [
        format_rename_suggestion(src, dst, colors=colors)
        for src, dst in context.copy_source_vs_context_source
        if src and dst
    ]
    if renames:
        msg += (
            f"However there are possible matches. Please review the following list of suggested "
            f"renames:\n\n{bullet_list(renames)}\n\n"
        )

    unknown = [src for src, dst in context.copy_source_vs_context_source if not dst]
    if unknown:
        msg += (
            f"The following files were not found in the Docker build context:\n\n"
            f"{bullet_list(unknown)}\n\n"
        )

    unreferenced = [dst for src, dst in context.copy_source_vs_context_source if not src]
    if unreferenced:
        if len(unreferenced) > 10:
            unreferenced = unreferenced[:9] + [f"... and {len(unreferenced)-9} more"]
        msg += (
            f"There are additional files in the Docker build context that were not referenced by "
            f"any `COPY` instruction (this is not an error):\n\n{bullet_list(unreferenced)}\n\n"
        )

    return msg


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
        UnionRule(RunFieldSet, DockerFieldSet),
    ]
