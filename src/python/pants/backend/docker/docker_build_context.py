# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain
from typing import Mapping

from pants.backend.docker.dockerfile_parser import DockerfileInfo
from pants.backend.docker.target_types import DockerImageSources
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.target_types import FileSourcesField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    SourcesBaseField,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


class DockerVersionContextError(ValueError):
    pass


class DockerVersionContextValue(FrozenDict[str, str]):
    """Dict class suitable for use as a format string context object, as it allows to use attribute
    access rather than item access."""

    def __getattr__(self, attribute: str) -> str:
        if attribute not in self:
            raise DockerVersionContextError(
                f"The key {attribute!r} is unknown. Try with one of: " f'{", ".join(self.keys())}.'
            )
        return self[attribute]


class DockerVersionContext(FrozenDict[str, DockerVersionContextValue]):
    def merge(self, other: Mapping[str, Mapping[str, str]]) -> DockerVersionContext:
        merged: dict[str, DockerVersionContextValue] = dict(self)
        merged.update({key: DockerVersionContextValue(value) for key, value in other.items()})
        return DockerVersionContext(merged)


@dataclass(frozen=True)
class DockerBuildContext:
    digest: Digest
    version_context: DockerVersionContext


@dataclass(frozen=True)
class DockerBuildContextRequest:
    address: Address
    build_upstream_images: bool = False


@rule
async def create_docker_build_context(request: DockerBuildContextRequest) -> DockerBuildContext:
    # Get all targets to include in context.
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([request.address]))

    # Get the Dockerfile from the root target.
    dockerfiles_request = Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[t.get(SourcesBaseField) for t in transitive_targets.roots],
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
            sources_fields=[t.get(SourcesBaseField) for t in chain(*root_dependencies)],
            for_sources_types=(FileSourcesField,),
        ),
    )

    embedded_pkgs_per_target_request = Get(
        FieldSetsPerTarget,
        FieldSetsPerTargetRequest(PackageFieldSet, transitive_targets.dependencies),
    )

    dockerfiles, sources, embedded_pkgs_per_target, dockerfile_info = await MultiGet(
        dockerfiles_request,
        sources_request,
        embedded_pkgs_per_target_request,
        Get(DockerfileInfo, DockerImageSources, transitive_targets.roots[0][DockerImageSources]),
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

    # Merge all digests to get the final docker build context.
    context = await Get(
        Digest,
        MergeDigests(d for d in all_digests if d),
    )

    version_context: dict[str, DockerVersionContextValue] = {}
    for stage, tag in [tag.split(maxsplit=1) for tag in dockerfile_info.version_tags]:
        value = DockerVersionContextValue({"tag": tag})
        if not version_context:
            # Refer to the first FROM directive as the "baseimage".
            version_context["baseimage"] = value
        version_context[stage] = value

    return DockerBuildContext(
        digest=context,
        version_context=DockerVersionContext(version_context),
    )


def rules():
    return collect_rules()
