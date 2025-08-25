# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
import shlex
from abc import ABC
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pants.backend.docker.package_types import BuiltDockerImage
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.subsystems.dockerfile_parser import (
    DockerfileInfo,
    DockerfileInfoRequest,
    parse_dockerfile,
)
from pants.backend.docker.target_types import DockerImageSourceField
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
    docker_build_args,
)
from pants.backend.docker.util_rules.docker_build_env import (
    DockerBuildEnvironment,
    DockerBuildEnvironmentError,
    DockerBuildEnvironmentRequest,
    docker_build_environment_vars,
)
from pants.backend.docker.utils import image_ref_regexp, suggest_renames
from pants.backend.docker.value_interpolation import DockerBuildArgsInterpolationValue
from pants.backend.shell.target_types import ShellSourceField
from pants.core.goals.package import (
    BuiltPackage,
    EnvironmentAwarePackageRequest,
    PackageFieldSet,
    environment_aware_package,
)
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.addresses import Address, UnparsedAddressInputs
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, MergeDigests, Snapshot
from pants.engine.internals.graph import (
    find_valid_field_sets,
    resolve_targets,
    resolve_unparsed_address_inputs,
)
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.intrinsics import digest_to_snapshot
from pants.engine.rules import collect_rules, concurrently, implicitly, rule, Get, MultiGet
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    SourcesField,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap, stable_hash
from pants.util.value_interpolation import InterpolationContext, InterpolationValue

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
    upstream_image_ids: tuple[str, ...]
    dockerfile: str
    interpolation_context: InterpolationContext
    copy_source_vs_context_source: tuple[tuple[str, str], ...]
    stages: tuple[str, ...]

    @classmethod
    def create(
        cls,
        build_args: DockerBuildArgs,
        snapshot: Snapshot,
        build_env: DockerBuildEnvironment,
        upstream_image_ids: Iterable[str],
        dockerfile_info: DockerfileInfo,
        should_suggest_renames: bool = True,
    ) -> DockerBuildContext:
        interpolation_context: dict[str, dict[str, str] | InterpolationValue] = {}

        if build_args:
            interpolation_context["build_args"] = cls._merge_build_args(
                dockerfile_info, build_args, build_env
            )

        # Override default value type for the `build_args` context to get helpful error messages.
        interpolation_context["build_args"] = DockerBuildArgsInterpolationValue(
            interpolation_context.get("build_args", {})
        )

        # Data from Pants.
        interpolation_context["pants"] = {
            # Present hash for all inputs that can be used for image tagging.
            "hash": stable_hash((build_args, build_env, snapshot.digest)),
        }

        # Base image tags values for all stages (as parsed from the Dockerfile instructions).
        stage_names, tags_values = cls._get_stages_and_tags(
            dockerfile_info, interpolation_context["build_args"]
        )
        interpolation_context["tags"] = tags_values

        copy_source_vs_context_source = (
            tuple(
                suggest_renames(
                    tentative_paths=(
                        # We don't want to include the Dockerfile as a suggested rename
                        dockerfile_info.source,
                        *dockerfile_info.copy_source_paths,
                    ),
                    actual_files=snapshot.files,
                    actual_dirs=snapshot.dirs,
                )
            )
            if should_suggest_renames
            else ()
        )

        return cls(
            build_args=build_args,
            digest=snapshot.digest,
            dockerfile=dockerfile_info.source,
            build_env=build_env,
            upstream_image_ids=tuple(sorted(upstream_image_ids)),
            interpolation_context=InterpolationContext.from_dict(interpolation_context),
            copy_source_vs_context_source=copy_source_vs_context_source,
            stages=tuple(sorted(stage_names)),
        )

    @classmethod
    def _get_stages_and_tags(
        cls, dockerfile_info: DockerfileInfo, build_args: Mapping[str, str]
    ) -> tuple[set[str], dict[str, str]]:
        # Go over all FROM tags and names for all stages.
        stage_names: set[str] = set()
        # tag is empty if image is referenced by digest instead
        stage_tags = ([*tag.split(maxsplit=1), ""][:2] for tag in dockerfile_info.version_tags)
        tags_values: dict[str, str] = {}
        for idx, (stage, tag) in enumerate(stage_tags):
            if tag.startswith("build-arg:"):
                build_arg = tag[10:]
                image_ref = build_args.get(build_arg) or dockerfile_info.build_args.to_dict().get(
                    build_arg
                )
                if not image_ref:
                    raise DockerBuildContextError(
                        f"Failed to parse Dockerfile baseimage tag for stage {stage} in "
                        f"{dockerfile_info.address} target, unknown build ARG: {build_arg!r}."
                    )
                parsed = re.match(image_ref_regexp, image_ref.strip("\"'"))
                tag = parsed.group("tag") or (parsed.group("digest") and "latest") if parsed else ""
                if not tag:
                    raise DockerBuildContextError(
                        f"Failed to parse Dockerfile baseimage tag for stage {stage} in "
                        f"{dockerfile_info.address} target, from image ref: {image_ref}."
                    )

            if stage != f"stage{idx}":
                stage_names.add(stage)
            if tag:
                if idx == 0:
                    # Expose the first (stage0) FROM directive as the "baseimage".
                    tags_values["baseimage"] = tag
                tags_values[stage] = tag

        return stage_names, tags_values

    @staticmethod
    def _merge_build_args(
        dockerfile_info: DockerfileInfo,
        build_args: DockerBuildArgs,
        build_env: DockerBuildEnvironment,
    ) -> dict[str, str]:
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
            return {
                arg_name: (
                    arg_value
                    if has_value
                    else build_env.get(arg_name, build_arg_defaults.get(arg_name))
                )
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


@rule
async def create_docker_build_context(
    request: DockerBuildContextRequest,
    options: DockerOptions,
) -> DockerBuildContext:
    # Get all targets to include in context.
    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest([request.address]), **implicitly()
    )
    docker_image = transitive_targets.roots[0]

    # Get all dependencies for the root target.
    root_dependencies = await resolve_targets(
        **implicitly(DependenciesRequest(docker_image.get(Dependencies)))
    )

    # Get all file sources from the root dependencies. That includes any non-file sources that can
    # be "codegen"ed into a file source.
    sources_request = determine_source_files(
        SourceFilesRequest(
            sources_fields=[tgt.get(SourcesField) for tgt in root_dependencies],
            for_sources_types=(
                DockerContextFilesSourcesField,
                FileSourceField,
            ),
            enable_codegen=True,
        )
    )

    embedded_pkgs_per_target_request = find_valid_field_sets(
        FieldSetsPerTargetRequest(PackageFieldSet, transitive_targets.dependencies), **implicitly()
    )

    sources, embedded_pkgs_per_target, dockerfile_info = await concurrently(
        sources_request,
        embedded_pkgs_per_target_request,
        parse_dockerfile(DockerfileInfoRequest(docker_image.address), **implicitly()),
    )

    # Package binary dependencies for build context.
    pkgs_wanting_embedding = [
        field_set
        for field_set in embedded_pkgs_per_target.field_sets
        # Exclude docker images, unless build_upstream_images is true.
        if (
            request.build_upstream_images
            or not isinstance(getattr(field_set, "source", None), DockerImageSourceField)
        )
    ]
    embedded_pkgs = await concurrently(
        environment_aware_package(EnvironmentAwarePackageRequest(field_set))
        for field_set in pkgs_wanting_embedding
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

    # Create digests for embedded packages. For upstream Docker images, we use only the image ID
    # to ensure hash stability. This prevents changes in image tags (which may include timestamps
    # or other dynamic values) from affecting the build context hash of dependent images.
    embedded_pkgs_digest = []
    
    # For Docker images, we need to extract the metadata filename and create stable digests
    docker_metadata_gets = []
    docker_package_indices = []
    for i, built_package in enumerate(embedded_pkgs):
        field_set = pkgs_wanting_embedding[i]
        if (
            request.build_upstream_images
            and isinstance(getattr(field_set, "source", None), DockerImageSourceField)
        ):
            docker_metadata_gets.append(Get(DigestContents, Digest, built_package.digest))
            docker_package_indices.append(i)
        else:
            # For non-Docker packages, use the regular digest
            embedded_pkgs_digest.append(built_package.digest)
    
    # Get metadata contents for Docker images
    if docker_metadata_gets:
        docker_metadata_contents = await MultiGet(*docker_metadata_gets)
        
        for metadata_contents, pkg_index in zip(docker_metadata_contents, docker_package_indices):
            built_package = embedded_pkgs[pkg_index]
            
            # Extract the original filename from the metadata
            if metadata_contents:
                original_filename = next(iter(metadata_contents)).path
                
                # Find the Docker image artifact to get the image ID
                for artifact in built_package.artifacts:
                    if isinstance(artifact, BuiltDockerImage):
                        stable_content = artifact.image_id.encode()
                        stable_digest = await Get(
                            Digest, CreateDigest([FileContent(original_filename, stable_content)])
                        )
                        embedded_pkgs_digest.append(stable_digest)
                        break
                else:
                    # Fallback if no BuiltDockerImage found (shouldn't happen)
                    embedded_pkgs_digest.append(built_package.digest)
            else:
                # Fallback if no contents in digest
                embedded_pkgs_digest.append(built_package.digest)

    all_digests = (dockerfile_info.digest, sources.snapshot.digest, *embedded_pkgs_digest)

    # Merge all digests to get the final docker build context digest.
    context_request = digest_to_snapshot(**implicitly(MergeDigests(d for d in all_digests if d)))

    # Requests for build args and env
    build_args_request = docker_build_args(DockerBuildArgsRequest(docker_image), **implicitly())
    build_env_request = docker_build_environment_vars(
        DockerBuildEnvironmentRequest(docker_image), **implicitly()
    )
    context, supplied_build_args, build_env = await concurrently(
        context_request, build_args_request, build_env_request
    )

    build_args = supplied_build_args

    upstream_image_ids = []
    if request.build_upstream_images:
        # Update build arg values for FROM image build args.

        # Get the FROM image build args with defined values in the Dockerfile & build args.
        dockerfile_build_args = dockerfile_info.from_image_build_args.with_overrides(
            supplied_build_args
        ).nonempty()
        # Parse the build args values into Address instances.
        from_image_addresses = await resolve_unparsed_address_inputs(
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
            **implicitly(),
        )
        # Map those addresses to the corresponding built image ref (tag).
        address_to_built_image_tag = {
            field_set.address: image.tags[0]
            for field_set, built in zip(embedded_pkgs_per_target.field_sets, embedded_pkgs)
            for image in built.artifacts
            if isinstance(image, BuiltDockerImage)
        }
        upstream_image_ids = [
            image.image_id
            for built in embedded_pkgs
            for image in built.artifacts
            if isinstance(image, BuiltDockerImage)
        ]
        # Create the FROM image build args.
        from_image_build_args = [
            f"{arg_name}={address_to_built_image_tag[addr]}"
            for arg_name, addr in zip(dockerfile_build_args.keys(), from_image_addresses)
        ]
        build_args = build_args.extended(from_image_build_args)

    # Render build args for turning COPY values in ARGS which are targets into their output
    dockerfile_copy_args = dockerfile_info.copy_build_args.with_overrides(
        supplied_build_args
    ).nonempty()

    def get_artifact_paths(built_package: BuiltPackage) -> list[str]:
        return [e.relpath for e in built_package.artifacts if e.relpath]

    addrs_to_paths = {
        field_set.address: get_artifact_paths(pkg)
        for field_set, pkg in zip(embedded_pkgs_per_target.field_sets, embedded_pkgs)
    }

    copy_arg_as_build_args = await fill_args_from_copy(
        dockerfile_copy_args, dockerfile_info, addrs_to_paths
    )

    build_args = build_args.extended(copy_arg_as_build_args)

    return DockerBuildContext.create(
        build_args=build_args,
        snapshot=context,
        upstream_image_ids=upstream_image_ids,
        dockerfile_info=dockerfile_info,
        build_env=build_env,
        should_suggest_renames=options.suggest_renames,
    )


async def fill_args_from_copy(
    dockerfile_copy_args: dict[str, str], dockerfile_info, addrs_to_paths
):
    copy_arg_addresses = await resolve_unparsed_address_inputs(
        UnparsedAddressInputs(
            dockerfile_info.copy_build_args.to_dict().values(),
            owning_address=dockerfile_info.address,
            description_of_origin=softwrap(
                f"""
                the COPY arguments from the file {dockerfile_info.source}
                from the target {dockerfile_info.address}
                """
            ),
            skip_invalid_addresses=True,
        ),
        **implicitly(),
    )

    def resolve_arg(arg_name, maybe_addr) -> str:
        if maybe_addr in addrs_to_paths:
            return f"{arg_name}={shlex.join(addrs_to_paths[maybe_addr])}"
        else:
            # When the ARG value is a reference to a normal file
            return f"{arg_name}={maybe_addr}"

    copy_arg_as_build_args = [
        resolve_arg(arg_name, arg_value)
        for arg_name, arg_value in (zip(dockerfile_copy_args.keys(), copy_arg_addresses))
    ]
    return copy_arg_as_build_args


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateDockerContextFiles),
    )
