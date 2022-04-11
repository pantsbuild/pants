# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass

from pants.backend.helm.resolve import fetch
from pants.backend.helm.resolve.artifacts import ResolvedHelmArtifact
from pants.backend.helm.resolve.fetch import (
    FetchedHelmArtifact,
    FetchedHelmArtifacts,
    FetchHelmArfifactsRequest,
)
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartMetaSourceField
from pants.backend.helm.util_rules import chart_metadata, sources
from pants.backend.helm.util_rules.chart_metadata import (
    HELM_CHART_METADATA_FILENAMES,
    HelmChartDependency,
    HelmChartMetadata,
    ParseHelmChartMetadataDigest,
)
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    DigestSubset,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, Target, Targets
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmChart:
    address: Address
    metadata: HelmChartMetadata
    snapshot: Snapshot
    artifact: ResolvedHelmArtifact | None = None

    @property
    def path(self) -> str:
        return self.metadata.name


@dataclass(frozen=True)
class HelmChartRequest:
    field_set: HelmChartFieldSet

    @classmethod
    def from_target(cls, target: Target) -> HelmChartRequest:
        return cls(HelmChartFieldSet.create(target))


@rule
async def create_chart_from_artifact(fetched_artifact: FetchedHelmArtifact) -> HelmChart:
    metadata = await Get(
        HelmChartMetadata,
        ParseHelmChartMetadataDigest(
            fetched_artifact.snapshot.digest,
            description_of_origin=fetched_artifact.address.spec,
            prefix=fetched_artifact.artifact.name,
        ),
    )
    return HelmChart(
        fetched_artifact.address,
        metadata,
        fetched_artifact.snapshot,
        artifact=fetched_artifact.artifact,
    )


@rule(desc="Collect all source code and subcharts of a Helm Chart", level=LogLevel.DEBUG)
async def get_helm_chart(request: HelmChartRequest, subsystem: HelmSubsystem) -> HelmChart:
    dependencies, source_files, metadata = await MultiGet(
        Get(Targets, DependenciesRequest(request.field_set.dependencies)),
        Get(
            HelmChartSourceFiles,
            HelmChartSourceFilesRequest,
            HelmChartSourceFilesRequest.for_field_set(
                request.field_set,
                include_metadata=False,
                include_resources=True,
                include_files=True,
            ),
        ),
        Get(HelmChartMetadata, HelmChartMetaSourceField, request.field_set.chart),
    )

    third_party_artifacts = await Get(
        FetchedHelmArtifacts,
        FetchHelmArfifactsRequest,
        FetchHelmArfifactsRequest.for_targets(
            dependencies, description_of_origin=request.field_set.address.spec
        ),
    )

    first_party_subcharts = await MultiGet(
        Get(HelmChart, HelmChartRequest, HelmChartRequest.from_target(target))
        for target in dependencies
        if HelmChartFieldSet.is_applicable(target)
    )
    third_party_charts = await MultiGet(
        Get(HelmChart, FetchedHelmArtifact, artifact) for artifact in third_party_artifacts
    )

    subcharts = [*first_party_subcharts, *third_party_charts]
    subcharts_digest = EMPTY_DIGEST
    if subcharts:
        logger.debug(
            f"Found {pluralize(len(subcharts), 'subchart')} as direct dependencies on Helm chart at: {request.field_set.address}"
        )

        merged_subcharts = await Get(
            Digest, MergeDigests([chart.snapshot.digest for chart in subcharts])
        )
        subcharts_digest = await Get(Digest, AddPrefix(merged_subcharts, "charts"))

        # Update subchart dependencies in the metadata and re-render it.
        remotes = subsystem.remotes()
        subchart_map: dict[str, HelmChart] = {chart.metadata.name: chart for chart in subcharts}
        updated_dependencies: OrderedSet[HelmChartDependency] = OrderedSet()
        for dep in metadata.dependencies:
            updated_dep = dep

            if not dep.repository and remotes.default_registry:
                # If the dependency hasn't specified a repository, then we choose the registry with the 'default' alias.
                default_remote = remotes.default_registry
                updated_dep = dataclasses.replace(updated_dep, repository=default_remote.address)
            elif dep.repository and dep.repository.startswith("@"):
                remote = next(remotes.get(dep.repository))
                updated_dep = dataclasses.replace(updated_dep, repository=remote.address)

            if dep.name in subchart_map:
                updated_dep = dataclasses.replace(
                    updated_dep, version=subchart_map[dep.name].metadata.version
                )

            updated_dependencies.add(updated_dep)

        # Include the explicitly provided subchats in the set of dependencies if not already present.
        updated_dependencies_names = {dep.name for dep in updated_dependencies}
        remaining_subcharts = [
            chart for chart in subcharts if chart.metadata.name not in updated_dependencies_names
        ]
        for chart in remaining_subcharts:
            if chart.artifact:
                dependency = HelmChartDependency(
                    name=chart.artifact.name,
                    version=chart.artifact.version,
                    repository=chart.artifact.location_url,
                )
            else:
                dependency = HelmChartDependency(
                    name=chart.metadata.name, version=chart.metadata.version
                )
            updated_dependencies.add(dependency)

        # Update metadata with the information about charts' dependencies.
        metadata = dataclasses.replace(metadata, dependencies=tuple(updated_dependencies))

    # Re-render the Chart.yaml file with the updated dependencies.
    metadata_digest, sources_without_metadata = await MultiGet(
        Get(Digest, HelmChartMetadata, metadata),
        Get(
            Digest,
            DigestSubset(
                source_files.snapshot.digest,
                PathGlobs(
                    ["**/*", *(f"!**/{filename}" for filename in HELM_CHART_METADATA_FILENAMES)]
                ),
            ),
        ),
    )

    # Merge all digests that conform chart's content.
    content_digest = await Get(
        Digest, MergeDigests([metadata_digest, sources_without_metadata, subcharts_digest])
    )

    chart_snapshot = await Get(Snapshot, AddPrefix(content_digest, metadata.name))
    return HelmChart(address=request.field_set.address, metadata=metadata, snapshot=chart_snapshot)


def rules():
    return [*collect_rules(), *sources.rules(), *chart_metadata.rules(), *fetch.rules()]
