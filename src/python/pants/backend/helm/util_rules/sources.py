# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartMetaSourceField,
    HelmChartSourcesField,
)
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, Snapshot
from pants.engine.internals.native_engine import RemovePrefix
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Target,
    Targets,
)


@dataclass(frozen=True)
class HelmChartRootRequest(EngineAwareParameter):
    source: HelmChartMetaSourceField

    def debug_hint(self) -> str | None:
        return self.source.address.spec


@dataclass(frozen=True)
class HelmChartRoot:
    path: str


@rule(desc="Detect Helm chart source root")
async def find_chart_source_root(request: HelmChartRootRequest) -> HelmChartRoot:
    source = await Get(
        HydratedSources,
        HydrateSourcesRequest(
            request.source, for_sources_types=[HelmChartMetaSourceField], enable_codegen=True
        ),
    )
    assert len(source.snapshot.files) == 1

    return HelmChartRoot(os.path.dirname(source.snapshot.files[0]))


@dataclass(frozen=True)
class HelmChartSourceFilesRequest(EngineAwareParameter):
    field_set: HelmChartFieldSet
    include_resources: bool
    include_files: bool
    include_metadata: bool

    @classmethod
    def create(
        cls,
        target: Target,
        *,
        include_resources: bool = True,
        include_files: bool = False,
        include_metadata: bool = True,
    ) -> HelmChartSourceFilesRequest:
        return cls.for_field_set(
            HelmChartFieldSet.create(target),
            include_resources=include_resources,
            include_files=include_files,
            include_metadata=include_metadata,
        )

    @classmethod
    def for_field_set(
        cls,
        field_set: HelmChartFieldSet,
        *,
        include_resources: bool = True,
        include_files: bool = False,
        include_metadata: bool = True,
    ) -> HelmChartSourceFilesRequest:
        return cls(
            field_set=field_set,
            include_resources=include_resources,
            include_files=include_files,
            include_metadata=include_metadata,
        )

    @property
    def sources_fields(self) -> tuple[SourcesField, ...]:
        fields: list[SourcesField] = [self.field_set.sources]
        if self.include_metadata:
            fields.append(self.field_set.chart)
        return tuple(fields)

    @property
    def valid_sources_types(self) -> tuple[type[SourcesField], ...]:
        types: list[type[SourcesField]] = [HelmChartSourcesField]
        if self.include_metadata:
            types.append(HelmChartMetaSourceField)
        if self.include_resources:
            types.append(ResourceSourceField)
        if self.include_files:
            types.append(FileSourceField)
        return tuple(types)

    def debug_hint(self) -> str | None:
        return self.field_set.address.spec


@dataclass(frozen=True)
class HelmChartSourceFiles:
    snapshot: Snapshot
    unrooted_files: tuple[str, ...]


async def _strip_chart_source_root(
    source_files: SourceFiles, chart_root: HelmChartRoot
) -> Snapshot:
    if not source_files.snapshot.files:
        return source_files.snapshot

    if source_files.unrooted_files:
        rooted_files = set(source_files.snapshot.files) - set(source_files.unrooted_files)
        rooted_files_snapshot = await Get(
            Snapshot, DigestSubset(source_files.snapshot.digest, PathGlobs(rooted_files))
        )
    else:
        rooted_files_snapshot = source_files.snapshot

    resulting_snapshot = await Get(
        Snapshot, RemovePrefix(rooted_files_snapshot.digest, chart_root.path)
    )
    if source_files.unrooted_files:
        # Add unrooted files back in
        unrooted_digest = await Get(
            Digest,
            DigestSubset(source_files.snapshot.digest, PathGlobs(source_files.unrooted_files)),
        )
        resulting_snapshot = await Get(
            Snapshot, MergeDigests([resulting_snapshot.digest, unrooted_digest])
        )

    return resulting_snapshot


@rule
async def get_helm_source_files(request: HelmChartSourceFilesRequest) -> HelmChartSourceFiles:
    chart_root, dependencies = await MultiGet(
        Get(HelmChartRoot, HelmChartRootRequest(request.field_set.chart)),
        Get(Targets, DependenciesRequest(request.field_set.dependencies)),
    )

    source_files, original_sources = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(
                sources_fields=[
                    *request.sources_fields,
                    *(
                        tgt.get(SourcesField)
                        for tgt in dependencies
                        if not HelmChartFieldSet.is_applicable(tgt)
                    ),
                ],
                for_sources_types=request.valid_sources_types,
                enable_codegen=True,
            ),
        ),
        Get(
            SourceFiles,
            SourceFilesRequest([request.field_set.sources], enable_codegen=False),
        ),
    )

    stripped_source_files = await _strip_chart_source_root(source_files, chart_root)
    stripped_original_sources = await _strip_chart_source_root(original_sources, chart_root)

    all_files_snapshot = await Get(
        Snapshot, MergeDigests([stripped_source_files.digest, stripped_original_sources.digest])
    )
    return HelmChartSourceFiles(
        snapshot=all_files_snapshot,
        unrooted_files=(*source_files.unrooted_files, *original_sources.unrooted_files),
    )


def rules():
    return [*collect_rules(), *source_files.rules()]
