# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.docker.target_types import DockerImageSources
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.target_types import FilesSources, ResourcesSources
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    Sources,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerBuildContext:
    digest: Digest


@dataclass(frozen=True)
class DockerBuildContextRequest:
    address: Address
    context_root: str
    build_upstream_images: bool = False


@rule
async def create_docker_build_context(request: DockerBuildContextRequest) -> DockerBuildContext:
    # Get all targets to include in context.
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([request.address]))

    # Get all dependencies from those root targets.
    all_dependencies = await MultiGet(
        Get(Targets, DependenciesRequest(target.get(Dependencies), include_special_cased_deps=True))
        for target in transitive_targets.roots
    )

    # Get Dockerfiles from all roots
    dockerfiles_request = Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[t.get(Sources) for t in transitive_targets.roots],
            for_sources_types=(DockerImageSources,),
        ),
    )
    # Get all sources from all dependencies (i.e. files and resources).
    sources_request = Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[t.get(Sources) for t in chain(*all_dependencies)],
            for_sources_types=(FilesSources, ResourcesSources),
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

    embedded_pkgs_digests = tuple(built_package.digest for built_package in embedded_pkgs)
    if request.context_root != ".":
        # Copy packages to context root tree, unless the context root is at the project root.
        embedded_pkgs_digests = await MultiGet(
            Get(Digest, AddPrefix(digest, request.context_root)) for digest in embedded_pkgs_digests
        )

    # Merge build context.
    context = await Get(
        Digest,
        MergeDigests(
            d
            for d in (
                dockerfiles.snapshot.digest,
                sources.snapshot.digest,
                *embedded_pkgs_digests,
            )
            if d
        ),
    )

    return DockerBuildContext(context)


def rules():
    return collect_rules()
