# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

import yaml

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
from pants.engine.target import DependenciesRequest, HydratedSources, HydrateSourcesRequest, Targets
from pants.util.logging import LogLevel
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


_DEFAULT_API_VERSION = "v1"


@dataclass(frozen=True)
class HelmChartMetadata:
    name: str
    version: str
    api_version: str = _DEFAULT_API_VERSION
    type: ChartType = ChartType.APPLICATION
    kube_version: str | None = None
    app_version: str | None = None
    icon: str | None = None
    description: str | None = None
    dependencies: tuple[HelmChartDependency, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmChartMetadata:
        deps = d.get("dependencies", [])

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
            "type": self.type.value,
        }
        if self.icon:
            d["icon"] = self.icon
        if self.description:
            d["description"] = self.description
        if self.app_version:
            d["appVersion"] = self.app_version
        if self.kube_version:
            d["kubeVersion"] = self.kube_version
        if self.dependencies:
            d["dependencies"] = list(self.dependencies)
        return d

    def to_yaml(self) -> str:
        return cast("str", yaml.dump(self.to_dict()))


@dataclass(frozen=True)
class HelmChart:
    address: Address
    metadata: HelmChartMetadata
    snapshot: Snapshot

    lint_strict: bool | None

    @property
    def path(self) -> str:
        return self.metadata.name


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
async def parse_chart_metadata_from_field(field: HelmChartMetaSourceField) -> HelmChartMetadata:
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
async def render_chart_metadata(metadata: HelmChartMetadata) -> Digest:
    digest = await Get(
        Digest,
        CreateDigest(
            [FileContent(_HELM_CHART_METADATA_FILENAMES[0], bytes(metadata.to_yaml(), "utf-8"))]
        ),
    )
    return digest


@rule(desc="Collect all source code and subcharts of a Helm Chart", level=LogLevel.DEBUG)
async def compile_chart_struct(field_set: HelmChartFieldSet) -> HelmChart:
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
            ),
        ),
        Get(HelmChartMetadata, HelmChartMetaSourceField, field_set.chart),
    )

    first_party_subcharts = await MultiGet(
        Get(HelmChart, HelmChartFieldSet, HelmChartFieldSet.create(target))
        for target in dependencies
        if HelmChartFieldSet.is_applicable(target)
    )
    logger.debug(
        f"Found {pluralize(len(first_party_subcharts), 'subchart')} as direct dependencies on Helm chart at: {field_set.address}"
    )

    # TODO Collect 3rd party chart dependencies (subcharts)
    subcharts = first_party_subcharts
    subcharts_digest = EMPTY_DIGEST
    if subcharts:
        merged_subcharts = await Get(
            Digest, MergeDigests([chart.snapshot.digest for chart in subcharts])
        )
        subcharts_digest = await Get(Digest, AddPrefix(merged_subcharts, "charts"))

        # TODO Update subchart dependencies in the metadata and re-render it (requires support for OCI registries and classic repositories)

    # Re-render the Chart.yaml file with the updated dependencies
    metadata_digest, sources_without_metadata = await MultiGet(
        Get(Digest, HelmChartMetadata, metadata),
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
        Digest, MergeDigests([metadata_digest, sources_without_metadata, subcharts_digest])
    )

    chart_snapshot = await Get(Snapshot, AddPrefix(all_sources, metadata.name))
    return HelmChart(
        address=field_set.address,
        metadata=metadata,
        snapshot=chart_snapshot,
        lint_strict=field_set.lint_strict.value,
    )


def rules():
    return collect_rules()
