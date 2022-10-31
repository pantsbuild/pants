# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import partial
from itertools import chain
from typing import Iterator, cast

# Re-exporting BuiltDockerImage here, as it has its natural home here, but has moved out to resolve
# a dependency cycle from docker_build_context.
from pants.backend.docker.package_types import BuiltDockerImage as BuiltDockerImage
from pants.backend.docker.registries import DockerRegistries, DockerRegistryOptions
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import (
    DockerBuildOptionFieldMixin,
    DockerBuildOptionFieldValueMixin,
    DockerBuildOptionFlagFieldMixin,
    DockerImageContextRootField,
    DockerImageRegistriesField,
    DockerImageRepositoryField,
    DockerImageSourceField,
    DockerImageTags,
    DockerImageTagsField,
    DockerImageTagsRequest,
    DockerImageTargetStageField,
)
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
)
from pants.backend.docker.utils import format_rename_suggestion
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunFieldSet
from pants.engine.addresses import Address
from pants.engine.process import FallibleProcessResult, Process, ProcessExecutionFailure
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target, WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import GlobalOptions, KeepSandboxes
from pants.util.strutil import bullet_list
from pants.util.value_interpolation import InterpolationContext, InterpolationError

logger = logging.getLogger(__name__)


class DockerImageTagValueError(InterpolationError):
    pass


class DockerRepositoryNameError(InterpolationError):
    pass


class DockerBuildTargetStageError(ValueError):
    pass


class DockerImageOptionValueError(ValueError):
    pass


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (DockerImageSourceField,)

    context_root: DockerImageContextRootField
    registries: DockerImageRegistriesField
    repository: DockerImageRepositoryField
    source: DockerImageSourceField
    tags: DockerImageTagsField
    target_stage: DockerImageTargetStageField

    def format_tag(self, tag: str, interpolation_context: InterpolationContext) -> str:
        source = InterpolationContext.TextSource(
            address=self.address, target_alias="docker_image", field_alias=self.tags.alias
        )
        return interpolation_context.format(tag, source=source, error_cls=DockerImageTagValueError)

    def format_repository(
        self,
        default_repository: str,
        interpolation_context: InterpolationContext,
        registry: DockerRegistryOptions | None = None,
    ) -> str:
        repository_context = InterpolationContext.from_dict(
            {
                "directory": os.path.basename(self.address.spec_path),
                "name": self.address.target_name,
                "parent_directory": os.path.basename(os.path.dirname(self.address.spec_path)),
                "default_repository": default_repository,
                "target_repository": self.repository.value or default_repository,
                **interpolation_context,
            }
        )
        if registry and registry.repository:
            repository_text = registry.repository
            source = InterpolationContext.TextSource(
                options_scope=f"[docker.registries.{registry.alias or registry.address}].repository"
            )
        elif self.repository.value:
            repository_text = self.repository.value
            source = InterpolationContext.TextSource(
                address=self.address, target_alias="docker_image", field_alias=self.repository.alias
            )
        else:
            repository_text = default_repository
            source = InterpolationContext.TextSource(options_scope="[docker].default_repository")
        return repository_context.format(
            repository_text, source=source, error_cls=DockerRepositoryNameError
        ).lower()

    def format_names(
        self,
        repository: str,
        tags: tuple[str, ...],
        interpolation_context: InterpolationContext,
    ) -> Iterator[str]:
        for tag in tags:
            yield ":".join(
                s for s in [repository, self.format_tag(tag, interpolation_context)] if s
            )

    def image_refs(
        self,
        default_repository: str,
        registries: DockerRegistries,
        interpolation_context: InterpolationContext,
        additional_tags: tuple[str, ...] = (),
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
        image_tags = (self.tags.value or ()) + additional_tags
        registries_options = tuple(registries.get(*(self.registries.value or [])))
        if not registries_options:
            # The image name is also valid as image ref without registry.
            repository = self.format_repository(default_repository, interpolation_context)
            return tuple(self.format_names(repository, image_tags, interpolation_context))

        return tuple(
            "/".join([registry.address, image_name])
            for registry in registries_options
            for image_name in self.format_names(
                self.format_repository(default_repository, interpolation_context, registry),
                image_tags + registry.extra_image_tags,
                interpolation_context,
            )
        )

    def get_context_root(self, default_context_root: str) -> str:
        """Examines `default_context_root` and `self.context_root.value` and translates that to a
        context root for the Docker build operation.

        That is, in the configuration/field value, the context root is relative to build root when
        in the form `path/..` (implies semantics as `//path/..` for target addresses) or the BUILD
        file when `./path/..`.

        The returned path is always relative to the build root.
        """
        if self.context_root.value is not None:
            context_root = self.context_root.value
        else:
            context_root = cast(
                str, self.context_root.compute_value(default_context_root, self.address)
            )
        if context_root.startswith("./"):
            context_root = os.path.join(self.address.spec_path, context_root)
        return os.path.normpath(context_root)


def get_build_options(
    context: DockerBuildContext,
    field_set: DockerFieldSet,
    global_target_stage_option: str | None,
    target: Target,
) -> Iterator[str]:
    # Build options from target fields inheriting from DockerBuildOptionFieldMixin
    for field_type in target.field_types:
        if issubclass(field_type, DockerBuildOptionFieldMixin):
            source = InterpolationContext.TextSource(
                address=target.address, target_alias=target.alias, field_alias=field_type.alias
            )
            format = partial(
                context.interpolation_context.format,
                source=source,
                error_cls=DockerImageOptionValueError,
            )
            yield from target[field_type].options(format)
        elif issubclass(field_type, DockerBuildOptionFieldValueMixin):
            yield from target[field_type].options()
        elif issubclass(field_type, DockerBuildOptionFlagFieldMixin):
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
    keep_sandboxes: KeepSandboxes,
    union_membership: UnionMembership,
) -> BuiltPackage:
    """Build a Docker image using `docker build`."""
    context, wrapped_target = await MultiGet(
        Get(
            DockerBuildContext,
            DockerBuildContextRequest(
                address=field_set.address,
                build_upstream_images=True,
            ),
        ),
        Get(
            WrappedTarget,
            WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
        ),
    )

    image_tags_requests = union_membership.get(DockerImageTagsRequest)
    additional_image_tags = await MultiGet(
        Get(DockerImageTags, DockerImageTagsRequest, image_tags_request_cls(wrapped_target.target))
        for image_tags_request_cls in image_tags_requests
        if image_tags_request_cls.is_applicable(wrapped_target.target)
    )

    tags = field_set.image_refs(
        default_repository=options.default_repository,
        registries=options.registries(),
        interpolation_context=context.interpolation_context,
        additional_tags=tuple(chain.from_iterable(additional_image_tags)),
    )

    # Mix the upstream image ids into the env to ensure that Pants invalidates this
    # image-building process correctly when an upstream image changes, even though the
    # process itself does not consume this data.
    env = {
        **context.build_env.environment,
        "__UPSTREAM_IMAGE_IDS": ",".join(context.upstream_image_ids),
    }
    context_root = field_set.get_context_root(options.default_context_root)
    process = docker.build_image(
        build_args=context.build_args,
        digest=context.digest,
        dockerfile=context.dockerfile,
        context_root=context_root,
        env=env,
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
        maybe_msg = format_docker_build_context_help_message(
            address=field_set.address,
            context_root=context_root,
            context=context,
            colors=global_options.colors,
        )
        if maybe_msg:
            logger.warning(maybe_msg)

        raise ProcessExecutionFailure(
            result.exit_code,
            result.stdout,
            result.stderr,
            process.description,
            keep_sandboxes=keep_sandboxes,
        )

    image_id = parse_image_id_from_docker_build_output(result.stdout, result.stderr)
    docker_build_output_msg = "\n".join(
        (
            f"Docker build output for {tags[0]}:",
            "stdout:",
            result.stdout.decode(),
            "stderr:",
            result.stderr.decode(),
        )
    )

    if options.build_verbose:
        logger.info(docker_build_output_msg)
    else:
        logger.debug(docker_build_output_msg)

    return BuiltPackage(
        result.output_digest,
        (BuiltDockerImage.create(image_id, tags),),
    )


def parse_image_id_from_docker_build_output(*outputs: bytes) -> str:
    """Outputs are typically the stdout/stderr pair from the `docker build` process."""
    # NB: We use the extracted image id for invalidation. The short_id may theoretically
    #  not be unique enough, although in a non adversarial situation, this is highly unlikely
    #  to be an issue in practice.
    image_id_regexp = re.compile(
        "|".join(
            (
                # BuildKit output.
                r"(writing image (?P<digest>sha256:\S+) done)",
                # Docker output.
                r"(Successfully built (?P<short_id>\S+))",
            ),
        )
    )
    for output in outputs:
        image_id_match = next(
            (
                match
                for match in (
                    re.search(image_id_regexp, line)
                    for line in reversed(output.decode().split("\n"))
                )
                if match
            ),
            None,
        )
        if image_id_match:
            image_id = image_id_match.group("digest") or image_id_match.group("short_id")
            return image_id

    return "<unknown>"


def format_docker_build_context_help_message(
    address: Address, context_root: str, context: DockerBuildContext, colors: bool
) -> str | None:
    paths_outside_context_root: list[str] = []

    def _chroot_context_paths(paths: tuple[str, str]) -> tuple[str, str]:
        """Adjust the context paths in `copy_source_vs_context_source` for `context_root`."""
        instruction_path, context_path = paths
        if not context_path:
            return paths
        dst = os.path.relpath(context_path, context_root)
        if dst.startswith("../"):
            paths_outside_context_root.append(context_path)
            return ("", "")
        if instruction_path == dst:
            return ("", "")
        return instruction_path, dst

    # Adjust context paths based on `context_root`.
    copy_source_vs_context_source: tuple[tuple[str, str], ...] = tuple(
        filter(any, map(_chroot_context_paths, context.copy_source_vs_context_source))
    )

    if not (copy_source_vs_context_source or paths_outside_context_root):
        # No issues found.
        return None

    msg = f"Docker build failed for `docker_image` {address}. "
    has_unsourced_copy = any(src for src, _ in copy_source_vs_context_source)
    if has_unsourced_copy:
        msg += (
            f"The {context.dockerfile} has `COPY` instructions for source files that may not have "
            f"been found in the Docker build context.\n\n"
        )

        renames = sorted(
            format_rename_suggestion(src, dst, colors=colors)
            for src, dst in copy_source_vs_context_source
            if src and dst
        )
        if renames:
            msg += (
                f"However there are possible matches. Please review the following list of "
                f"suggested renames:\n\n{bullet_list(renames)}\n\n"
            )

        unknown = sorted(src for src, dst in copy_source_vs_context_source if src and not dst)
        if unknown:
            msg += (
                f"The following files were not found in the Docker build context:\n\n"
                f"{bullet_list(unknown)}\n\n"
            )

    unreferenced = sorted(dst for src, dst in copy_source_vs_context_source if dst and not src)
    if unreferenced:
        msg += (
            f"There are files in the Docker build context that were not referenced by "
            f"any `COPY` instruction (this is not an error):\n\n{bullet_list(unreferenced, 10)}\n\n"
        )

    if paths_outside_context_root:
        unreachable = sorted({os.path.dirname(pth) for pth in paths_outside_context_root})
        context_paths = tuple(dst for src, dst in context.copy_source_vs_context_source if dst)
        new_context_root = os.path.commonpath(context_paths)
        msg += (
            "There are unreachable files in these directories, excluded from the build context "
            f"due to `context_root` being {context_root!r}:\n\n{bullet_list(unreachable, 10)}\n\n"
            f"Suggested `context_root` setting is {new_context_root!r} in order to include all "
            "files in the build context, otherwise relocate the files to be part of the current "
            f"`context_root` {context_root!r}."
        )

    return msg


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
        UnionRule(RunFieldSet, DockerFieldSet),
    ]
