# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, cast

import yaml

from pants.backend.helm.resolve.artifacts import ThirdPartyArtifactMapping
from pants.backend.helm.resolve.fetch import (
    FetchedHelmArtifact,
    FetchedHelmArtifacts,
    FetchHelmArfifactsRequest,
)
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartMetaSourceField
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    GlobExpansionConjunction,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class ChartType(Enum):
    """Type of Helm Chart."""

    APPLICATION = "application"
    LIBRARY = "library"


class InvalidChartTypeValueError(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(
            f"Invalid value '{value}' for Helm Chart `type`. Valid values are: {[t.value for t in list(ChartType)]}"
        )


@dataclass(frozen=True)
class HelmChartDependency:
    name: str
    repository: str | None = None
    version: str | None = None
    alias: str | None = None
    condition: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmChartDependency:
        return cls(
            name=d["name"],
            repository=d.get("repository"),
            alias=d.get("alias"),
            condition=d.get("condition"),
            version=d.get("version"),
        )

    @property
    def alias_or_name(self) -> str:
        return self.alias or self.name

    @property
    def location(self) -> str:
        repo = self.repository or ""
        return f"{repo}/{self.alias_or_name}".lstrip("/")


class HelmChartDependencies(OrderedSet[HelmChartDependency]):
    pass


_DEFAULT_API_VERSION = "v1"


@dataclass(frozen=True)
class HelmChartMetadata:
    name: str
    version: str
    api_version: str = _DEFAULT_API_VERSION
    kube_version: str | None = None
    app_version: str | None = None
    icon: str | None = None
    description: str | None = None
    dependencies: tuple[HelmChartDependency, ...] = field(default_factory=tuple)
    type: ChartType = ChartType.APPLICATION

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmChartMetadata:
        deps = d.get("dependencies") or []

        chart_type: ChartType | None = None
        type_str = d.get("type")
        if type_str:
            try:
                chart_type = ChartType(type_str)
            except KeyError:
                raise InvalidChartTypeValueError(type_str)

        return cls(
            api_version=d.get("apiVersion", _DEFAULT_API_VERSION),
            name=d["name"],
            version=d["version"],
            icon=d.get("icon"),
            app_version=d.get("appVersion"),
            kube_version=d.get("kubeVersion"),
            description=d.get("description"),
            dependencies=tuple([HelmChartDependency.from_dict(dep) for dep in deps]),
            type=chart_type or ChartType.APPLICATION,
        )

    @classmethod
    def from_bytes(cls, content: bytes) -> HelmChartMetadata:
        return cls.from_dict(yaml.safe_load(content))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "apiVersion": self.api_version,
            "name": self.name,
            "version": self.version,
            "icon": self.icon,
            "description": self.description,
            "dependencies": list(self.dependencies),
            "type": self.type.value,
        }
        if self.app_version:
            d["appVersion"] = self.app_version
        if self.kube_version:
            d["kubeVersion"] = self.kube_version
        return d

    def to_yaml(self) -> str:
        return cast("str", yaml.dump(self.to_dict()))


@dataclass(frozen=True)
class HelmChart:
    address: Address
    metadata: HelmChartMetadata
    snapshot: Snapshot

    @property
    def path(self) -> str:
        return self.metadata.name


@dataclass(frozen=True)
class RenderedHelmChartMetadata:
    digest: Digest


class InferHelmChartDependenciesRequest(InferDependenciesRequest):
    infer_from = HelmChartMetaSourceField


_HELM_CHART_METADATA_FILENAMES = ["Chart.yaml", "Chart.yml"]


def _chart_metadata_subset(digest: Digest) -> DigestSubset:
    globs = PathGlobs(
        [f"**/{filename}" for filename in _HELM_CHART_METADATA_FILENAMES],
        glob_match_error_behavior=GlobMatchErrorBehavior.error,
        conjunction=GlobExpansionConjunction.any_match,
        description_of_origin="parse_chart_metadata",
    )
    return DigestSubset(digest, globs)


@rule
async def chart_metadata_from_field(field: HelmChartMetaSourceField) -> HelmChartMetadata:
    source_files = await Get(
        HydratedSources,
        HydrateSourcesRequest(
            field, for_sources_types=(HelmChartMetaSourceField,), enable_codegen=True
        ),
    )
    subset = await Get(Digest, DigestSubset, _chart_metadata_subset(source_files.snapshot.digest))
    file_contents = await Get(DigestContents, Digest, subset)
    return HelmChartMetadata.from_bytes(file_contents[0].content)


@rule
async def render_chart_metadata(metadata: HelmChartMetadata) -> RenderedHelmChartMetadata:
    digest = await Get(
        Digest,
        CreateDigest(
            [FileContent(_HELM_CHART_METADATA_FILENAMES[0], bytes(metadata.to_yaml(), "utf-8"))]
        ),
    )
    return RenderedHelmChartMetadata(digest)


@rule
async def create_chart_from_artifact(artifact: FetchedHelmArtifact) -> HelmChart:
    subset = await Get(Digest, DigestSubset, _chart_metadata_subset(artifact.snapshot.digest))
    file_contents = await Get(DigestContents, Digest, subset)
    # TODO this should not be needed as the DigestSubset should have returned a Digest with only one file
    metadata = [
        HelmChartMetadata.from_bytes(entry.content)
        for entry in file_contents
        if os.path.basename(entry.path) in _HELM_CHART_METADATA_FILENAMES
    ]
    # metadata = HelmChartMetadata.from_bytes(file_contents[0].content)
    return HelmChart(artifact.address, metadata[0], artifact.snapshot)


@rule(desc="Collect all source code of a Helm Chart", level=LogLevel.DEBUG)
async def gather_chart_sources(field_set: HelmChartFieldSet, config: HelmSubsystem) -> HelmChart:
    dependencies, source_files, metadata = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies)),
        Get(
            HelmChartSourceFiles,
            HelmChartSourceFilesRequest,
            HelmChartSourceFilesRequest.for_field_set(
                field_set,
                include_metadata=False,
                include_resources=True,
                include_files=True,
                generate_docs=True,
            ),
        ),
        Get(HelmChartMetadata, HelmChartMetaSourceField, field_set.chart),
    )

    first_party_subcharts = await MultiGet(
        Get(HelmChart, HelmChartFieldSet, HelmChartFieldSet.create(target))
        for target in dependencies
        if HelmChartFieldSet.is_applicable(target)
    )
    third_party_artifacts = await Get(
        FetchedHelmArtifacts,
        FetchHelmArfifactsRequest,
        FetchHelmArfifactsRequest.for_targets(dependencies),
    )
    third_party_subcharts = await MultiGet(
        Get(HelmChart, FetchedHelmArtifact, artifact) for artifact in third_party_artifacts
    )

    # Package subchart dependencies
    subcharts = [*first_party_subcharts, *third_party_subcharts]
    subcharts_digest = EMPTY_DIGEST
    if subcharts:
        merged_subcharts = await Get(
            Digest, MergeDigests([chart.snapshot.digest for chart in subcharts])
        )
        subcharts_digest = await Get(Digest, AddPrefix(merged_subcharts, "charts"))

        # Update subchart dependencies in the metadata and re-render it
        registries = config.registries()
        subchart_map: dict[str, HelmChart] = {chart.metadata.name: chart for chart in subcharts}
        new_dependencies = []
        for dep in metadata.dependencies:
            updated_dep = dep

            if not dep.repository and registries.default:
                # If the dependency hasn't specified a repository, then we choose the first default registry
                updated_dep = replace(updated_dep, repository=f"@{registries.default[0]}")
            elif dep.repository and dep.repository.startswith("oci://"):
                # If repository has been set in the dependency, then try to replace it by an alias
                address = config.strip_default_repository_from_oci_address(dep.repository)
                alias = registries.get_alias_of(address)
                if alias:
                    updated_dep = replace(updated_dep, repository=f"@{alias}")

            if dep.name in subchart_map:
                updated_dep = replace(updated_dep, version=subchart_map[dep.name].metadata.version)

            new_dependencies.append(updated_dep)

        metadata = replace(metadata, dependencies=tuple(new_dependencies))

    # Re-render the Chart.yaml file with the updated dependencies
    rendered_metadata, sources_without_metadata = await MultiGet(
        Get(RenderedHelmChartMetadata, HelmChartMetadata, metadata),
        Get(
            Digest,
            DigestSubset(
                source_files.snapshot.digest,
                PathGlobs(
                    ["**/*", *(f"!**/{filename}" for filename in _HELM_CHART_METADATA_FILENAMES)]
                ),
            ),
        ),
    )

    # Merge all sources together
    all_sources = await Get(
        Digest, MergeDigests([rendered_metadata.digest, sources_without_metadata, subcharts_digest])
    )

    chart_snapshot = await Get(Snapshot, AddPrefix(all_sources, metadata.name))
    return HelmChart(address=field_set.address, metadata=metadata, snapshot=chart_snapshot)


@rule(desc="Inferring Helm chart dependencies", level=LogLevel.DEBUG)
async def infer_chart_dependencies_via_metadata(
    request: InferHelmChartDependenciesRequest,
    all_targets: AllTargets,
    third_party_mapping: ThirdPartyArtifactMapping,
) -> InferredDependencies:
    # Build a mapping between the available Helm chart targets and their names
    first_party_chart_mapping: dict[str, Address] = {}
    chart_tgts = [tgt for tgt in all_targets if HelmChartFieldSet.is_applicable(tgt)]
    for tgt in chart_tgts:
        first_party_chart_mapping[tgt.address.target_name] = tgt.address

    # Parse Chart.yaml for explicitly set dependencies
    metadata = await Get(HelmChartMetadata, HelmChartMetaSourceField, request.sources_field)

    # Associate dependencies in Chart.yaml with addresses
    dependencies: OrderedSet[Address] = OrderedSet()
    for chart_dep in metadata.dependencies:
        # Check if this is a third party dependency declared as `helm_artifact`
        artifact_addr = third_party_mapping.get(chart_dep.location)
        if artifact_addr:
            dependencies.add(artifact_addr)
            continue

        # Treat the dependency as a first party one
        dependencies.add(first_party_chart_mapping[chart_dep.name])

    logging.debug(
        f"Inferred {pluralize(len(dependencies), 'dependency')} for target at address: {request.sources_field.address}"
    )
    return InferredDependencies(dependencies)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferHelmChartDependenciesRequest),
    ]
