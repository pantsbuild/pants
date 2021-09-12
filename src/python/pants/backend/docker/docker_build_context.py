# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from itertools import chain

from pants.backend.docker.target_types import DockerImageSources
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.target_types import FilesSources
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import Digest, MergeDigests, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    Sources,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionMembership, union

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerBuildContext:
    digest: Digest


@union
@dataclass(frozen=True)  # type: ignore[misc]
class DockerBuildContextPlugin(ABC):
    """Hook to offer plugins the possibility to customize the Docker build context used when
    building Docker images.

    The snapshot is the complete context for docker_image target. A plugin may implement a rule to
    modify that digest, and return a new DockerBuildContext.

    Example rule to customize the context:

        class CustomContext(DockerBuildContextPlugin):
            is_applicable(cls, target):
                return True

        @rule
        async def plugin_rule(request: CustomContext) -> DockerBuildContext:
            context = await Get(...)
            return DockerBuildContext(context)
    """

    snapshot: Snapshot
    target: Target

    @classmethod
    @abstractmethod
    def is_applicable(cls, target: Target) -> bool:
        """Whether the build context plugin should be used for this target or not."""


@dataclass(frozen=True)
class DockerBuildContextRequest:
    address: Address
    build_upstream_images: bool = False


@rule
async def create_docker_build_context(
    request: DockerBuildContextRequest, union_membership: UnionMembership
) -> DockerBuildContext:
    # Get all targets to include in context.
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([request.address]))

    # Get the Dockerfile from the root target.
    dockerfiles_request = Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[t.get(Sources) for t in transitive_targets.roots],
            for_sources_types=(DockerImageSources,),
        ),
    )

    # Get all dependencies for the root target.
    root_dependencies = await MultiGet(
        Get(Targets, DependenciesRequest(target.get(Dependencies)))
        for target in transitive_targets.roots
    )

    # Get all sources from the root dependencies (i.e. files).
    sources_request = Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[t.get(Sources) for t in chain(*root_dependencies)],
            for_sources_types=(FilesSources,),
        ),
    )

    embedded_pkgs_per_target_request = Get(
        FieldSetsPerTarget,
        FieldSetsPerTargetRequest(PackageFieldSet, transitive_targets.dependencies),
    )

    dockerfiles, sources, embedded_pkgs_per_target = await MultiGet(
        dockerfiles_request,
        sources_request,
        embedded_pkgs_per_target_request,
    )

    # Package binary dependencies for build context.
    embedded_pkgs = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set)
        for field_set in embedded_pkgs_per_target.field_sets
        # Exclude docker images, unless build_upstream_images is true.
        if request.build_upstream_images
        or not isinstance(getattr(field_set, "sources", None), DockerImageSources)
    )

    packages_str = ", ".join(a.relpath for p in embedded_pkgs for a in p.artifacts if a.relpath)
    logger.debug(f"Packages for Docker image: {packages_str}")

    embedded_pkgs_digest = [built_package.digest for built_package in embedded_pkgs]
    all_digests = (dockerfiles.snapshot.digest, sources.snapshot.digest, *embedded_pkgs_digest)

    # Merge all digests to get the docker build context.
    context = await Get(
        Snapshot,
        MergeDigests(d for d in all_digests if d),
    )

    target = transitive_targets.roots[0]

    # Call plugins that may modify build context.
    customized_contexts = await MultiGet(
        Get(
            DockerBuildContext,
            DockerBuildContextPlugin,  # type: ignore[misc]
            plugin(snapshot=context, target=target),  # type: ignore[abstract]
        )
        for plugin in union_membership.get(DockerBuildContextPlugin)
        if plugin.is_applicable(target)
    )

    if not customized_contexts:
        final_context = context.digest
    else:
        final_context = await Get(Digest, MergeDigests(c.digest for c in customized_contexts))

    return DockerBuildContext(final_context)


def rules():
    return collect_rules()
