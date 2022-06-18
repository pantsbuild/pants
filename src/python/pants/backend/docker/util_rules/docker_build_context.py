# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass

from pants.backend.docker.package_types import BuiltDockerImage
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo, DockerfileInfoRequest
from pants.backend.docker.target_types import DockerImageSourceField
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
)
from pants.backend.docker.util_rules.docker_build_env import (
    DockerBuildEnvironment,
    DockerBuildEnvironmentError,
    DockerBuildEnvironmentRequest,
)
from pants.backend.docker.utils import get_hash, suggest_renames
from pants.backend.docker.value_interpolation import (
    DockerBuildArgsInterpolationValue,
    DockerInterpolationContext,
    DockerInterpolationValue,
)
from pants.backend.shell.target_types import ShellSourceField
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.fs import Digest, MergeDigests, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    SourcesField,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class DockerBuildContextError(Exception):
    pass


class DockerContextFilesAcceptableInputsField(ABC, SourcesField):
    """This is a meta field for the context files generator, to tell the codegen machinery what
    source fields are good to use as-is.

    Use `DockerContextFilesAcceptableInputsField.register(<SourceField>)` to register input fields
    that should be accepted.

    This is implemented using the `ABC.register` from Python lib:
    https://docs.python.org/3/library/abc.html#abc.ABCMeta.register
    """


# These sources will be used to populate the build context as-is.
DockerContextFilesAcceptableInputsField.register(ShellSourceField)


class DockerContextFilesSourcesField(SourcesField):
    """This is just a type marker for the codegen machinery."""


class GenerateDockerContextFiles(GenerateSourcesRequest):
    """This translates all files from acceptable Source fields for the docker context using the
    `codegen` machinery."""

    input = DockerContextFilesAcceptableInputsField
    output = DockerContextFilesSourcesField
    exportable = False


@rule
async def hydrate_input_sources(request: GenerateDockerContextFiles) -> GeneratedSources:
    # We simply pass the files on, as-is
    return GeneratedSources(request.protocol_sources)


@dataclass(frozen=True)
class DockerBuildContextRequest:
    address: Address
    build_upstream_images: bool = False


@dataclass(frozen=True)
class DockerBuildContext:
    build_args: DockerBuildArgs
    digest: Digest
    build_env: DockerBuildEnvironment
    dockerfile: str
    interpolation_context: DockerInterpolationContext
    copy_source_vs_context_source: tuple[tuple[str, str], ...]
    stages: tuple[str, ...]

    @classmethod
    def create(
        cls,
        build_args: DockerBuildArgs,
        snapshot: Snapshot,
        build_env: DockerBuildEnvironment,
        dockerfile_info: DockerfileInfo,
    ) -> DockerBuildContext:
        interpolation_context: dict[str, dict[str, str] | DockerInterpolationValue] = {}

        # Go over all FROM tags and names for all stages.
        stage_names: set[str] = set()
        stage_tags = (tag.split(maxsplit=1) for tag in dockerfile_info.version_tags)
        tags_values: dict[str, str] = {}
        for idx, (stage, tag) in enumerate(stage_tags):
            if stage != f"stage{idx}":
                stage_names.add(stage)
            if idx == 0:
                # Expose the first (stage0) FROM directive as the "baseimage".
                tags_values["baseimage"] = tag
            tags_values[stage] = tag

        if build_args:
            # Extract default arg values from the parsed Dockerfile.
            build_arg_defaults = {
                def_name: def_value
                for def_name, has_default, def_value in [
                    def_arg.partition("=") for def_arg in dockerfile_info.build_args
                ]
                if has_default
            }
            try:
                # Create build args context value, based on defined build_args and
                # extra_build_args. We do _not_ auto "magically" pick up all ARG names from the
                # Dockerfile as first class args to use as placeholders, to make it more explicit
                # which args are actually being used by Pants. We do pick up any defined default ARG
                # values from the Dockerfile however, in order to not having to duplicate them in
                # the BUILD files.
                interpolation_context["build_args"] = {
                    arg_name: arg_value
                    if has_value
                    else build_env.get(arg_name, build_arg_defaults.get(arg_name))
                    for arg_name, has_value, arg_value in [
                        build_arg.partition("=") for build_arg in build_args
                    ]
                }
            except DockerBuildEnvironmentError as e:
                raise DockerBuildContextError(
                    f"Undefined value for build arg on the {dockerfile_info.address} target: {e}"
                    "\n\nIf you did not intend to inherit the value for this build arg from the "
                    "environment, provide a default value with the option `[docker].build_args` "
                    "or in the `extra_build_args` field on the target definition. Alternatively, "
                    "you may also provide a default value on the `ARG` instruction directly in "
                    "the `Dockerfile`."
                ) from e

        # Override default value type for the `build_args` context to get helpful error messages.
        interpolation_context["build_args"] = DockerBuildArgsInterpolationValue(
            interpolation_context.get("build_args", {})
        )

        # Data from Pants.
        interpolation_context["pants"] = {
            # Present hash for all inputs that can be used for image tagging.
            "hash": get_hash((build_args, build_env, snapshot.digest)).hexdigest(),
        }

        # Base image tags values for all stages (as parsed from the Dockerfile instructions).
        interpolation_context["tags"] = tags_values

        return cls(
            build_args=build_args,
            digest=snapshot.digest,
            dockerfile=dockerfile_info.source,
            build_env=build_env,
            interpolation_context=DockerInterpolationContext.from_dict(interpolation_context),
            copy_source_vs_context_source=tuple(
                suggest_renames(
                    tentative_paths=(
                        # We don't want to include the Dockerfile as a suggested rename
                        dockerfile_info.source,
                        *dockerfile_info.copy_source_paths,
                    ),
                    actual_files=snapshot.files,
                    actual_dirs=snapshot.dirs,
                )
            ),
            stages=tuple(sorted(stage_names)),
        )


@rule
async def create_docker_build_context(
    request: DockerBuildContextRequest, docker_options: DockerOptions
) -> DockerBuildContext:
    # Get all targets to include in context.
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([request.address]))
    docker_image = transitive_targets.roots[0]

    # Get all dependencies for the root target.
    root_dependencies = await Get(Targets, DependenciesRequest(docker_image.get(Dependencies)))

    # Get all file sources from the root dependencies. That includes any non-file sources that can
    # be "codegen"ed into a file source.
    sources_request = Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[tgt.get(SourcesField) for tgt in root_dependencies],
            for_sources_types=(
                DockerContextFilesSourcesField,
                FileSourceField,
            ),
            enable_codegen=True,
        ),
    )

    embedded_pkgs_per_target_request = Get(
        FieldSetsPerTarget,
        FieldSetsPerTargetRequest(PackageFieldSet, transitive_targets.dependencies),
    )

    sources, embedded_pkgs_per_target, dockerfile_info = await MultiGet(
        sources_request,
        embedded_pkgs_per_target_request,
        Get(DockerfileInfo, DockerfileInfoRequest(docker_image.address)),
    )

    # Package binary dependencies for build context.
    embedded_pkgs = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set)
        for field_set in embedded_pkgs_per_target.field_sets
        # Exclude docker images, unless build_upstream_images is true.
        if (
            request.build_upstream_images
            or not isinstance(getattr(field_set, "source", None), DockerImageSourceField)
        )
    )

    if request.build_upstream_images:
        images_str = ", ".join(
            a.tags[0] for p in embedded_pkgs for a in p.artifacts if isinstance(a, BuiltDockerImage)
        )
        if images_str:
            logger.debug(f"Built upstream Docker images: {images_str}")
        else:
            logger.debug("Did not build any upstream Docker images")

    packages_str = ", ".join(a.relpath for p in embedded_pkgs for a in p.artifacts if a.relpath)
    if packages_str:
        logger.debug(f"Built packages for Docker image: {packages_str}")
    else:
        logger.debug("Did not build any packages for Docker image")

    embedded_pkgs_digest = [built_package.digest for built_package in embedded_pkgs]
    all_digests = (dockerfile_info.digest, sources.snapshot.digest, *embedded_pkgs_digest)

    # Merge all digests to get the final docker build context digest.
    context_request = Get(Snapshot, MergeDigests(d for d in all_digests if d))

    # Requests for build args and env
    build_args_request = Get(DockerBuildArgs, DockerBuildArgsRequest(docker_image))
    build_env_request = Get(DockerBuildEnvironment, DockerBuildEnvironmentRequest(docker_image))
    context, build_args, build_env = await MultiGet(
        context_request, build_args_request, build_env_request
    )

    if request.build_upstream_images:
        # Update build arg values for FROM image build args.

        # Get the FROM image build args with defined values in the Dockerfile.
        dockerfile_build_args = {
            k: v for k, v in dockerfile_info.from_image_build_args.to_dict().items() if v
        }

        # Parse the build args values into Address instances.
        from_image_addresses = await Get(
            Addresses,
            UnparsedAddressInputs(
                dockerfile_build_args.values(),
                owning_address=dockerfile_info.address,
                description_of_origin=softwrap(
                    f"""
                    the FROM arguments from the file {dockerfile_info.source}
                    from the target {dockerfile_info.address}
                    """
                ),
                skip_invalid_addresses=True,
            ),
        )
        # Map those addresses to the corresponding built image ref (tag).
        address_to_built_image_tag = {
            field_set.address: image.tags[0]
            for field_set, built in zip(embedded_pkgs_per_target.field_sets, embedded_pkgs)
            for image in built.artifacts
            if isinstance(image, BuiltDockerImage)
        }
        # Create the FROM image build args.
        from_image_build_args = [
            f"{arg_name}={address_to_built_image_tag[addr]}"
            for arg_name, addr in zip(dockerfile_build_args.keys(), from_image_addresses)
        ]
        # Merge all build args.
        build_args = DockerBuildArgs.from_strings(*build_args, *from_image_build_args)

    return DockerBuildContext.create(
        build_args=build_args,
        snapshot=context,
        dockerfile_info=dockerfile_info,
        build_env=build_env,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateDockerContextFiles),
    )
