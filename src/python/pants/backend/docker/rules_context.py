# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from itertools import chain
from typing import Tuple

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
    Target,
    Targets,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerBuildContext:
    digest: Digest


@dataclass(frozen=True)
class DockerBuildContextRequest:
    address: Address
    context_root: str
    targets: Tuple[Target, ...]


@rule
async def create_docker_build_context(request: DockerBuildContextRequest) -> DockerBuildContext:
    # Get all sources, going into the build context.
    sources_request = Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[t.get(Sources) for t in request.targets],
            for_sources_types=(DockerImageSources, FilesSources, ResourcesSources),
        ),
    )

    # Get all dependent targets.
    dependencies_targets = await MultiGet(
        Get(Targets, DependenciesRequest(t.get(Dependencies))) for t in request.targets
    )

    embedded_pkg_tgts = tuple(chain(*dependencies_targets))
    logger.debug(
        f"""Get packages for Docker image from: {", ".join(str(t.address) for t in embedded_pkg_tgts)}"""
    )

    sources, dependencies_field_sets_per_target = await MultiGet(
        sources_request,
        Get(FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, embedded_pkg_tgts)),
    )

    # Package binary dependencies for build context.
    embedded_packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set)
        for field_set in dependencies_field_sets_per_target.field_sets
    )

    packages_str = ", ".join(a.relpath for p in embedded_packages for a in p.artifacts if a.relpath)
    logger.debug(f"Packages for Docker image: {packages_str}")

    embedded_pkgs_digests = tuple(built_package.digest for built_package in embedded_packages)
    if request.context_root != ".":
        # Copy packages to context root, unless the context root is at the project root
        embedded_pkgs_digests = await MultiGet(
            Get(Digest, AddPrefix(digest, request.context_root)) for digest in embedded_pkgs_digests
        )

    # Merge build context.
    context = await Get(
        Digest,
        MergeDigests(
            d
            for d in (
                sources.snapshot.digest,
                *embedded_pkgs_digests,
            )
            if d
        ),
    )

    return DockerBuildContext(context)


def rules():
    return collect_rules()
