# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

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
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    SourcesField,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


class DockerBuildContextError(Exception):
    pass


class DockerVersionContextError(ValueError):
    pass


class DockerVersionContextValue(FrozenDict[str, str]):
    """Dict class suitable for use as a format string context object, as it allows to use attribute
    access rather than item access."""

    def __getattr__(self, attribute: str) -> str:
        if attribute not in self:
            raise DockerVersionContextError(
                f"The placeholder {attribute!r} is unknown. Try with one of: "
                f'{", ".join(self.keys())}.'
            )
        return self[attribute]


class DockerVersionContext(FrozenDict[str, DockerVersionContextValue]):
    @classmethod
    def from_dict(cls, data: Mapping[str, Mapping[str, str]]) -> DockerVersionContext:
        return DockerVersionContext(
            {key: DockerVersionContextValue(value) for key, value in data.items()}
        )

    def merge(self, other: Mapping[str, Mapping[str, str]]) -> DockerVersionContext:
        return DockerVersionContext.from_dict({**self, **other})


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
    version_context: DockerVersionContext

    @classmethod
    def create(
        cls,
        build_args: DockerBuildArgs,
        digest: Digest,
        build_env: DockerBuildEnvironment,
        dockerfile_info: DockerfileInfo,
    ) -> DockerBuildContext:
        version_context: dict[str, dict[str, str]] = {}

        # FROM tags for all stages.
        for stage, tag in [tag.split(maxsplit=1) for tag in dockerfile_info.version_tags]:
            value = {"tag": tag}
            if not version_context:
                # Expose the first (stage0) FROM directive as the "baseimage".
                version_context["baseimage"] = value
            version_context[stage] = value

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
                version_context["build_args"] = {
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
                    "environment, provide a default value where it is defined either in "
                    "`[docker].build_args` or in the `extra_build_args` field on the target "
                    "definition. Alternatively, you may also provide a default value on the `ARG` "
                    "instruction in the `Dockerfile`."
                ) from e

        return cls(
            build_args=build_args,
            digest=digest,
            dockerfile=dockerfile_info.source,
            build_env=build_env,
            version_context=DockerVersionContext.from_dict(version_context),
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

    # Get all sources from the root dependencies (i.e. files).
    file_sources_request = Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[tgt.get(SourcesField) for tgt in root_dependencies],
            for_sources_types=(FileSourceField,),
            enable_codegen=True,
        ),
    )

    embedded_pkgs_per_target_request = Get(
        FieldSetsPerTarget,
        FieldSetsPerTargetRequest(PackageFieldSet, transitive_targets.dependencies),
    )

    file_sources, embedded_pkgs_per_target, dockerfile_info = await MultiGet(
        file_sources_request,
        embedded_pkgs_per_target_request,
        Get(DockerfileInfo, DockerfileInfoRequest(docker_image.address)),
    )

    # Package binary dependencies for build context.
    embedded_pkgs = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set)
        for field_set in embedded_pkgs_per_target.field_sets
        # Exclude docker images, unless build_upstream_images is true.
        if request.build_upstream_images
        or not isinstance(getattr(field_set, "sources", None), DockerImageSourceField)
    )

    packages_str = ", ".join(a.relpath for p in embedded_pkgs for a in p.artifacts if a.relpath)
    logger.debug(f"Packages for Docker image: {packages_str}")

    embedded_pkgs_digest = [built_package.digest for built_package in embedded_pkgs]
    all_digests = (dockerfile_info.digest, file_sources.snapshot.digest, *embedded_pkgs_digest)

    # Merge all digests to get the final docker build context digest.
    context_request = Get(Digest, MergeDigests(d for d in all_digests if d))

    # Requests for build args and env
    build_args_request = Get(DockerBuildArgs, DockerBuildArgsRequest(docker_image))
    build_env_request = Get(DockerBuildEnvironment, DockerBuildEnvironmentRequest(docker_image))
    context, build_args, build_env = await MultiGet(
        context_request, build_args_request, build_env_request
    )

    return DockerBuildContext.create(
        build_args=build_args,
        digest=context,
        dockerfile_info=dockerfile_info,
        build_env=build_env,
    )


def rules():
    return collect_rules()
