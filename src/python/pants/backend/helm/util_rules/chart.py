# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

import yaml

from pants.backend.helm.resolve import fetch
from pants.backend.helm.resolve.fetch import (
    FetchedHelmArtifact,
    FetchedHelmArtifacts,
    FetchHelmArfifactsRequest,
)
from pants.backend.helm.resolve.remotes import OCI_REGISTRY_PROTOCOL, HelmRemotes
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartMetaSourceField
from pants.backend.helm.util_rules import sources
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.backend.helm.util_rules.tool import HelmProcess
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
from pants.engine.process import ProcessResult
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
            d["repository"] = self.repository.rstrip("/")
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

    def remote_spec(self, remotes: HelmRemotes) -> str:
        if not self.repository:
            registry = remotes.default_registry
            if registry:
                return f"{registry.address}/{self.name}"
            return self.name
        elif self.repository.startswith(OCI_REGISTRY_PROTOCOL):
            return f"{self.repository}/{self.name}"
        else:
            remote = remotes.all[self.repository]
            return f"{remote.alias}/{self.name}"


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

        # If the `apiVersion` is missing in the original `dict`, then we assume we are dealing with `v1` charts.
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
    generate_chart_lockfile: bool = False

    @classmethod
    def from_target(
        cls, target: Target, *, generate_chart_lockfile: bool = False
    ) -> HelmChartRequest:
        return cls(
            HelmChartFieldSet.create(target), generate_chart_lockfile=generate_chart_lockfile
        )


_HELM_CHART_METADATA_FILENAMES = ["Chart.yaml", "Chart.yml"]


def _chart_metadata_subset(
    digest: Digest, *, description_of_origin: str, prefix: str | None = None
) -> DigestSubset:
    def prefixed_filename(filename: str) -> str:
        if not prefix:
            return filename
        return os.path.join(prefix, filename)

    glob_exprs = [prefixed_filename(filename) for filename in _HELM_CHART_METADATA_FILENAMES]
    globs = PathGlobs(
        glob_exprs,
        glob_match_error_behavior=GlobMatchErrorBehavior.error,
        conjunction=GlobExpansionConjunction.any_match,
        description_of_origin=description_of_origin,
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
    subset = await Get(
        Digest,
        DigestSubset,
        _chart_metadata_subset(
            source_files.snapshot.digest,
            description_of_origin="rule parse_chart_metadata_from_field",
            prefix="**",
        ),
    )
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


@rule
async def create_chart_from_artifact(fetched_artifact: FetchedHelmArtifact) -> HelmChart:
    subset = await Get(
        Digest,
        DigestSubset,
        _chart_metadata_subset(
            fetched_artifact.snapshot.digest,
            description_of_origin="rule create_chart_from_artifact",
            prefix=fetched_artifact.artifact.name,
        ),
    )
    file_contents = await Get(DigestContents, Digest, subset)
    assert len(file_contents) == 1

    metadata = HelmChartMetadata.from_bytes(file_contents[0].content)
    return HelmChart(fetched_artifact.address, metadata, fetched_artifact.snapshot)


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
        FetchHelmArfifactsRequest.for_targets(dependencies),
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
        updated_dependencies = []
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

            updated_dependencies.append(updated_dep)

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
                    ["**/*", *(f"!**/{filename}" for filename in _HELM_CHART_METADATA_FILENAMES)]
                ),
            ),
        ),
    )

    # Merge all digests that conform chart's content.
    content_digest = await Get(
        Digest, MergeDigests([metadata_digest, sources_without_metadata, subcharts_digest])
    )

    # Re-generate Chart.lock file (charts that have no dependencies, will not produce a Chart.lock file).
    if request.generate_chart_lockfile:
        chart_lockfile_result = await Get(
            ProcessResult,
            HelmProcess(
                argv=["dependency", "build", ".", "--skip-refresh"],
                input_digest=content_digest,
                description=f"Rebuild Helm chart lockfile for: {metadata.name}",
                output_files=("Chart.lock",),
            ),
        )
        content_digest = await Get(
            Digest, MergeDigests([content_digest, chart_lockfile_result.output_digest])
        )

    chart_snapshot = await Get(Snapshot, AddPrefix(content_digest, metadata.name))
    return HelmChart(
        address=request.field_set.address,
        metadata=metadata,
        snapshot=chart_snapshot,
    )


def rules():
    return [*collect_rules(), *sources.rules(), *fetch.rules()]
