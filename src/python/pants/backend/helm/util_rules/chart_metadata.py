# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

import yaml

from pants.backend.helm.target_types import HelmChartMetaSourceField
from pants.backend.helm.util_rules.sources import HelmChartRootRequest, find_chart_source_root
from pants.backend.helm.utils.yaml import snake_case_attr_dict
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestSubset,
    FileContent,
    GlobExpansionConjunction,
    PathGlobs,
)
from pants.engine.internals.graph import hydrate_sources
from pants.engine.internals.native_engine import RemovePrefix
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import (
    create_digest,
    digest_subset_to_digest,
    get_digest_contents,
    remove_prefix,
)
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import HydrateSourcesRequest
from pants.util.frozendict import FrozenDict
from pants.util.strutil import bullet_list


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
    tags: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    import_values: tuple[str, ...] = dataclasses.field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmChartDependency:
        attrs = snake_case_attr_dict(d)

        tags = attrs.pop("tags", [])
        import_values = attrs.pop("import_values", [])

        return cls(tags=tuple(tags), import_values=tuple(import_values), **attrs)

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
    dependencies: tuple[HelmChartDependency, ...] = dataclasses.field(default_factory=tuple)
    keywords: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    sources: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    home: str | None = None
    maintainers: tuple[HelmChartMaintainer, ...] = dataclasses.field(default_factory=tuple)
    deprecated: bool | None = None
    annotations: FrozenDict[str, str] = dataclasses.field(default_factory=FrozenDict)

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

    def to_json_dict(self) -> dict[str, Any]:
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
            d["annotations"] = dict(self.annotations.items())
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
        return cast("str", yaml.dump(self.to_json_dict()))


HELM_CHART_METADATA_FILENAMES = ["Chart.yaml", "Chart.yml"]


@dataclass(frozen=True)
class ParseHelmChartMetadataDigest(EngineAwareParameter):
    """Request to parse the Helm chart definition file (i.e. `Chart.yaml`) from the given digest.

    The definition file is expected to be at the root of the digest.
    """

    digest: Digest
    description_of_origin: str

    def debug_hint(self) -> str | None:
        return self.description_of_origin


@rule
async def parse_chart_metadata_from_digest(
    request: ParseHelmChartMetadataDigest,
) -> HelmChartMetadata:
    subset = await digest_subset_to_digest(
        DigestSubset(
            request.digest,
            PathGlobs(
                HELM_CHART_METADATA_FILENAMES,
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                conjunction=GlobExpansionConjunction.any_match,
                description_of_origin=request.description_of_origin,
            ),
        )
    )

    file_contents = await get_digest_contents(subset)

    if len(file_contents) == 0:
        raise MissingChartMetadataException(
            f"Could not find any file that matched with either {HELM_CHART_METADATA_FILENAMES} in target at {request.description_of_origin}."
        )
    if len(file_contents) > 1:
        raise AmbiguousChartMetadataException(
            f"Found more than one Helm chart metadata file at '{request.description_of_origin}':\n{bullet_list([f.path for f in file_contents])}"
        )

    return HelmChartMetadata.from_bytes(file_contents[0].content)


@rule
async def parse_chart_metadata_from_field(field: HelmChartMetaSourceField) -> HelmChartMetadata:
    chart_root, source_files = await concurrently(
        find_chart_source_root(HelmChartRootRequest(field)),
        hydrate_sources(
            HydrateSourcesRequest(
                field, for_sources_types=(HelmChartMetaSourceField,), enable_codegen=True
            ),
            **implicitly(),
        ),
    )

    metadata_digest = await remove_prefix(
        RemovePrefix(source_files.snapshot.digest, chart_root.path)
    )

    return await parse_chart_metadata_from_digest(
        ParseHelmChartMetadataDigest(
            metadata_digest,
            description_of_origin=f"the `helm_chart` {field.address.spec}",
        )
    )


@rule
async def render_chart_metadata(metadata: HelmChartMetadata) -> Digest:
    yaml_contents = bytes(metadata.to_yaml(), "utf-8")
    return await create_digest(
        CreateDigest([FileContent(HELM_CHART_METADATA_FILENAMES[0], yaml_contents)])
    )


def rules():
    return collect_rules()
