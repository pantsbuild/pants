# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

import yaml

from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartMetaSourceField
from pants.backend.helm.util_rules import sources
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.backend.helm.util_rules.yaml_utils import snake_case_attr_dict
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
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    Target,
    Targets,
)
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, pluralize

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


class MissingChartMetadataException(Exception):
    pass


class AmbiguousChartMetadataException(Exception):
    pass


@dataclass(frozen=True)
class HelmChartDependency:
    name: str
    repository: str | None = None
    version: str | None = None
    alias: str | None = None
    condition: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    import_values: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmChartDependency:
        return cls(**snake_case_attr_dict(d))

    def to_json_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.repository:
            d["repository"] = self.repository
        if self.version:
            d["version"] = self.version
        if self.alias:
            d["alias"] = self.alias
        if self.condition:
            d["condition"] = self.condition
        if self.tags:
            d["tags"] = list(self.tags)
        if self.import_values:
            d["import-values"] = list(self.import_values)
        return d


@dataclass(frozen=True)
class HelmChartMaintainer:
    name: str
    email: str | None = None
    url: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmChartMaintainer:
        return cls(**d)

    def to_json_dict(self) -> dict[str, Any]:
        d = {"name": self.name}
        if self.email:
            d["email"] = self.email
        if self.url:
            d["url"] = self.url
        return d


DEFAULT_API_VERSION = "v2"


@dataclass(frozen=True)
class HelmChartMetadata:
    name: str
    version: str
    api_version: str = DEFAULT_API_VERSION
    type: ChartType = ChartType.APPLICATION
    kube_version: str | None = None
    app_version: str | None = None
    icon: str | None = None
    description: str | None = None
    dependencies: tuple[HelmChartDependency, ...] = field(default_factory=tuple)
    keywords: tuple[str, ...] = field(default_factory=tuple)
    sources: tuple[str, ...] = field(default_factory=tuple)
    home: str | None = None
    maintainers: tuple[HelmChartMaintainer, ...] = field(default_factory=tuple)
    deprecated: bool | None = None
    annotations: FrozenDict[str, str] = field(default_factory=FrozenDict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmChartMetadata:
        chart_type: ChartType | None = None
        type_str = d.pop("type", None)
        if type_str:
            try:
                chart_type = ChartType(type_str)
            except KeyError:
                raise InvalidChartTypeValueError(type_str)

        # If the `apiVersion` is missing in the original `dict`, then we assume we are dealing with `v1` charts
        api_version = d.pop("apiVersion", "v1")
        dependencies = [HelmChartDependency.from_dict(d) for d in d.pop("dependencies", [])]
        maintainers = [HelmChartMaintainer.from_dict(d) for d in d.pop("maintainers", [])]
        keywords = d.pop("keywords", [])
        sources = d.pop("sources", [])
        annotations = d.pop("annotations", {})

        attrs = snake_case_attr_dict(d)

        return cls(
            api_version=api_version,
            dependencies=tuple(dependencies),
            maintainers=tuple(maintainers),
            keywords=tuple(keywords),
            type=chart_type or ChartType.APPLICATION,
            annotations=FrozenDict(annotations),
            sources=tuple(sources),
            **attrs,
        )

    @classmethod
    def from_bytes(cls, content: bytes) -> HelmChartMetadata:
        return cls.from_dict(yaml.safe_load(content))

    @property
    def artifact_name(self) -> str:
        return f"{self.name}-{self.version}"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "apiVersion": self.api_version,
            "name": self.name,
            "version": self.version,
        }
        if self.api_version != "v1":
            d["type"] = self.type.value
        if self.icon:
            d["icon"] = self.icon
        if self.description:
            d["description"] = self.description
        if self.app_version:
            d["appVersion"] = self.app_version
        if self.kube_version:
            d["kubeVersion"] = self.kube_version
        if self.dependencies:
            d["dependencies"] = [item.to_json_dict() for item in self.dependencies]
        if self.maintainers:
            d["maintainers"] = [item.to_json_dict() for item in self.maintainers]
        if self.annotations:
            d["annotations"] = {key: value for key, value in self.annotations.items()}
        if self.keywords:
            d["keywords"] = list(self.keywords)
        if self.sources:
            d["sources"] = list(self.sources)
        if self.home:
            d["home"] = self.home
        if self.deprecated:
            d["deprecated"] = self.deprecated
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
class HelmChartRequest:
    field_set: HelmChartFieldSet

    @classmethod
    def from_target(cls, target: Target) -> HelmChartRequest:
        return cls(HelmChartFieldSet.create(target))


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

    if len(file_contents) == 0:
        raise MissingChartMetadataException(
            f"Could not find any file that matched with either {_HELM_CHART_METADATA_FILENAMES} in target at: {field.address}"
        )
    if len(file_contents) > 1:
        raise AmbiguousChartMetadataException(
            f"Found more than one Helm chart metadata file at address '{field.address}':\n{bullet_list([f.path for f in file_contents])}"
        )

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
async def get_helm_chart(request: HelmChartRequest) -> HelmChart:
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

    first_party_subcharts = await MultiGet(
        Get(HelmChart, HelmChartRequest, HelmChartRequest.from_target(target))
        for target in dependencies
        if HelmChartFieldSet.is_applicable(target)
    )
    logger.debug(
        f"Found {pluralize(len(first_party_subcharts), 'subchart')} as direct dependencies on Helm chart at: {request.field_set.address}"
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
        address=request.field_set.address,
        metadata=metadata,
        snapshot=chart_snapshot,
    )


def rules():
    return [*collect_rules(), *sources.rules()]
