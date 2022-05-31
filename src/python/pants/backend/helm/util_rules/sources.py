# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartMetaSourceField,
    HelmChartSourcesField,
)
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import MergeDigests, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, SourcesField, Target, Targets


@dataclass(frozen=True)
class HelmChartSourceFilesRequest:
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


@dataclass(frozen=True)
class HelmChartSourceFiles:
    snapshot: Snapshot


@rule
async def get_helm_source_files(request: HelmChartSourceFilesRequest) -> HelmChartSourceFiles:
    dependencies = await Get(Targets, DependenciesRequest(request.field_set.dependencies))
    source_files, original_sources = await MultiGet(
        Get(
            StrippedSourceFiles,
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
            StrippedSourceFiles,
            SourceFilesRequest([request.field_set.sources], enable_codegen=False),
        ),
    )
    all_files_snapshot = await Get(
        Snapshot, MergeDigests([source_files.snapshot.digest, original_sources.snapshot.digest])
    )
    return HelmChartSourceFiles(snapshot=all_files_snapshot)


def rules():
    return collect_rules()
