# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Any, Iterable

from pants.backend.helm.dependency_inference import chart as chart_inference
from pants.backend.helm.resolve import fetch
from pants.backend.helm.resolve.artifacts import ResolvedHelmArtifact
from pants.backend.helm.resolve.fetch import FetchedHelmArtifact, FetchHelmArtifactRequest
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmArtifactFieldSet,
    HelmChartFieldSet,
    HelmChartMetaSourceField,
    HelmChartTarget,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.util_rules import chart_metadata, sources
from pants.backend.helm.util_rules.chart_metadata import (
    HELM_CHART_METADATA_FILENAMES,
    HelmChartDependency,
    HelmChartMetadata,
    ParseHelmChartMetadataDigest,
)
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    DigestSubset,
    FileDigest,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.internals.native_engine import AddressInput
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    Target,
    Targets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)


class InvalidHelmChartTarget(ValueError):
    def __init__(self, target: Target) -> None:
        super().__init__(f"The target {target.address} is not a `{HelmChartTarget.alias}`.")


@dataclass(frozen=True)
class HelmChart(EngineAwareReturnType):
    address: Address
    info: HelmChartMetadata
    snapshot: Snapshot
    artifact: ResolvedHelmArtifact | None = None

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def description(self) -> str:
        return self.name

    @property
    def immutable_input_digests(self) -> FrozenDict[str, Digest]:
        return FrozenDict({self.name: self.snapshot.digest})

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        msg = f"Built Helm chart '{self.info.name}' from target at {self.address}"
        if self.artifact:
            msg += f" (resolved using URL {self.artifact.chart_url})."
        return msg

    def metadata(self) -> dict[str, Any] | None:
        meta: dict[str, Any] = {"name": self.info.name, "address": self.address.spec}
        if self.artifact:
            meta["artifact"] = self.artifact
        return meta

    def artifacts(self) -> dict[str, FileDigest | Snapshot] | None:
        return {"snapshot": self.snapshot}


@dataclass(frozen=True)
class HelmChartRequest(EngineAwareParameter):
    field_set: HelmChartFieldSet

    @classmethod
    def from_target(cls, target: Target) -> HelmChartRequest:
        if not HelmChartFieldSet.is_applicable(target):
            raise InvalidHelmChartTarget(target)
        return cls(HelmChartFieldSet.create(target))

    def debug_hint(self) -> str | None:
        return self.field_set.address.spec

    def metadata(self) -> dict[str, Any] | None:
        return {"address": self.field_set.address.spec}


@rule(desc="Compile third parth Helm chart", level=LogLevel.DEBUG)
async def create_chart_from_artifact(fetched_artifact: FetchedHelmArtifact) -> HelmChart:
    metadata = await Get(
        HelmChartMetadata,
        ParseHelmChartMetadataDigest(
            fetched_artifact.snapshot.digest,
            description_of_origin=f"the `helm_artifact` {fetched_artifact.address}",
        ),
    )
    return HelmChart(
        fetched_artifact.address,
        metadata,
        fetched_artifact.snapshot,
        artifact=fetched_artifact.artifact,
    )


async def _merge_subchart_digests(charts: Iterable[HelmChart]) -> Digest:
    prefixed_chart_digests = await MultiGet(
        Get(Digest, AddPrefix(chart.snapshot.digest, chart.name)) for chart in charts
    )
    merged_digests = await Get(Digest, MergeDigests(prefixed_chart_digests))
    return await Get(Digest, AddPrefix(merged_digests, "charts"))


async def _find_charts_by_targets(
    targets: Iterable[Target], *, description_of_origin: str
) -> tuple[HelmChart, ...]:
    requests = [
        *(
            Get(HelmChart, HelmChartRequest, HelmChartRequest.from_target(target))
            for target in targets
            if HelmChartFieldSet.is_applicable(target)
        ),
        *(
            Get(
                HelmChart,
                FetchHelmArtifactRequest,
                FetchHelmArtifactRequest.from_target(
                    target,
                    description_of_origin=description_of_origin,
                ),
            )
            for target in targets
            if HelmArtifactFieldSet.is_applicable(target)
        ),
    ]
    return await MultiGet(requests)


@rule(desc="Compile Helm chart", level=LogLevel.DEBUG)
async def get_helm_chart(request: HelmChartRequest, subsystem: HelmSubsystem) -> HelmChart:
    dependencies, source_files, chart_info = await MultiGet(
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

    if request.field_set.version.value:
        chart_info = dataclasses.replace(chart_info, version=request.field_set.version.value)

    subcharts_digest = EMPTY_DIGEST
    subcharts = await _find_charts_by_targets(
        dependencies, description_of_origin=f"the `helm_chart` {request.field_set.address}"
    )
    if subcharts:
        logger.debug(
            softwrap(
                f"""
                Found {pluralize(len(subcharts), 'subchart')} as direct dependencies
                on Helm chart at: {request.field_set.address}.
                """
            )
        )

        subcharts_digest = await _merge_subchart_digests(subcharts)

        # Update subchart dependencies in the metadata and re-render it.
        remotes = subsystem.remotes()
        subchart_map: dict[str, HelmChart] = {chart.info.name: chart for chart in subcharts}
        updated_dependencies: OrderedSet[HelmChartDependency] = OrderedSet()
        for dep in chart_info.dependencies:
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
                    updated_dep, version=subchart_map[dep.name].info.version
                )

            updated_dependencies.add(updated_dep)

        # Include the explicitly provided subchats in the set of dependencies if not already present.
        updated_dependencies_names = {dep.name for dep in updated_dependencies}
        remaining_subcharts = [
            chart for chart in subcharts if chart.info.name not in updated_dependencies_names
        ]
        for chart in remaining_subcharts:
            if chart.artifact:
                dependency = HelmChartDependency(
                    name=chart.artifact.name,
                    version=chart.artifact.version,
                    repository=chart.artifact.location_url,
                )
            else:
                dependency = HelmChartDependency(name=chart.info.name, version=chart.info.version)
            updated_dependencies.add(dependency)

        # Update metadata with the information about charts' dependencies.
        chart_info = dataclasses.replace(chart_info, dependencies=tuple(updated_dependencies))

    # Re-render the Chart.yaml file with the updated dependencies.
    metadata_digest, sources_without_metadata = await MultiGet(
        Get(Digest, HelmChartMetadata, chart_info),
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
    chart_snapshot = await Get(
        Snapshot, MergeDigests([metadata_digest, sources_without_metadata, subcharts_digest])
    )

    return HelmChart(address=request.field_set.address, info=chart_info, snapshot=chart_snapshot)


@dataclass(frozen=True)
class FindHelmDeploymentChart(EngineAwareParameter):
    field_set: HelmDeploymentFieldSet

    def debug_hint(self) -> str | None:
        return self.field_set.address.spec


@rule(desc="Find Helm deployment's chart", level=LogLevel.DEBUG)
async def find_chart_for_deployment(request: FindHelmDeploymentChart) -> HelmChart:
    address_input = request.field_set.chart.to_address_input()
    address = await Get(Address, AddressInput, address_input)
    wrapped_target = await Get(
        WrappedTarget, WrappedTargetRequest(address, address_input.description_of_origin)
    )

    found_charts = await _find_charts_by_targets(
        [wrapped_target.target],
        description_of_origin=f"the `helm_deployment` {request.field_set.address}",
    )
    assert len(found_charts) == 1
    return found_charts[0]


def rules():
    return [
        *collect_rules(),
        *sources.rules(),
        *chart_metadata.rules(),
        *chart_inference.rules(),
        *fetch.rules(),
    ]
