# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, Tuple, Union

from pants.base.specs import AddressSpec, OriginSpec
from pants.engine.fs import DirectoriesToMerge, PathGlobs, Snapshot, SnapshotSubset
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.target import Sources as SourcesField
from pants.rules.core import strip_source_roots
from pants.rules.core.strip_source_roots import SourceRootStrippedSources, StripSourcesFieldRequest
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class SourceFiles:
    """A merged snapshot of the `sources` fields of multiple targets, possibly containing a subset
    of the `sources` when using `SpecifiedSourceFilesRequest` (instead of
    `AllSourceFilesRequest`)."""

    snapshot: Snapshot

    @property
    def files(self) -> Tuple[str, ...]:
        return self.snapshot.files


@frozen_after_init
@dataclass(unsafe_hash=True)
class AllSourceFilesRequest:
    sources_fields: Tuple[SourcesField, ...]
    strip_source_roots: bool = False

    def __init__(
        self, sources_fields: Iterable[SourcesField], *, strip_source_roots: bool = False
    ) -> None:
        self.sources_fields = tuple(sources_fields)
        self.strip_source_roots = strip_source_roots


@frozen_after_init
@dataclass(unsafe_hash=True)
class SpecifiedSourceFilesRequest:
    sources_fields_with_origins: Tuple[Tuple[SourcesField, OriginSpec], ...]
    strip_source_roots: bool = False

    def __init__(
        self,
        sources_fields_with_origins: Iterable[Tuple[SourcesField, OriginSpec]],
        *,
        strip_source_roots: bool = False
    ) -> None:
        self.sources_fields_with_origins = tuple(sources_fields_with_origins)
        self.strip_source_roots = strip_source_roots


def calculate_specified_sources(
    sources_snapshot: Snapshot, origin: OriginSpec
) -> Union[Snapshot, SnapshotSubset]:
    # AddressSpecs simply use the entire `sources` field.
    if isinstance(origin, AddressSpec):
        return sources_snapshot
    # NB: we ensure that `precise_files_specified` is a subset of the original `sources` field.
    # It's possible when given a glob filesystem spec that the spec will have
    # resolved files not belonging to this target - those must be filtered out.
    precise_files_specified = set(sources_snapshot.files).intersection(origin.resolved_files)
    return SnapshotSubset(
        directory_digest=sources_snapshot.directory_digest,
        globs=PathGlobs(sorted(precise_files_specified)),
    )


@rule
async def determine_all_source_files(request: AllSourceFilesRequest) -> SourceFiles:
    """Merge all `Sources` fields into one Snapshot."""
    if request.strip_source_roots:
        stripped_snapshots = await MultiGet(
            Get[SourceRootStrippedSources](StripSourcesFieldRequest(sources_field))
            for sources_field in request.sources_fields
        )
        digests_to_merge = tuple(
            stripped_snapshot.snapshot.directory_digest for stripped_snapshot in stripped_snapshots
        )
    else:
        all_hydrated_sources = await MultiGet(
            Get[HydratedSources](HydrateSourcesRequest, sources_field.request)
            for sources_field in request.sources_fields
        )
        digests_to_merge = tuple(
            hydrated_sources.snapshot.directory_digest for hydrated_sources in all_hydrated_sources
        )
    result = await Get[Snapshot](DirectoriesToMerge(digests_to_merge))
    return SourceFiles(result)


@rule
async def determine_specified_source_files(request: SpecifiedSourceFilesRequest) -> SourceFiles:
    """Determine the specified `sources` for targets, possibly finding a subset of the original
    `sources` fields if the user supplied file arguments."""
    all_hydrated_sources = await MultiGet(
        Get[HydratedSources](HydrateSourcesRequest, sources_field_with_origin[0].request)
        for sources_field_with_origin in request.sources_fields_with_origins
    )

    full_snapshots = {}
    snapshot_subset_requests = {}
    for hydrated_sources, sources_field_with_origin in zip(
        all_hydrated_sources, request.sources_fields_with_origins
    ):
        sources_field, origin = sources_field_with_origin
        if not hydrated_sources.snapshot.files:
            continue
        result = calculate_specified_sources(hydrated_sources.snapshot, origin)
        if isinstance(result, Snapshot):
            full_snapshots[sources_field] = result
        else:
            snapshot_subset_requests[sources_field] = result

    snapshot_subsets: Tuple[Snapshot, ...] = ()
    if snapshot_subset_requests:
        snapshot_subsets = await MultiGet(
            Get[Snapshot](SnapshotSubset, request) for request in snapshot_subset_requests.values()
        )

    all_snapshots: Iterable[Snapshot] = (*full_snapshots.values(), *snapshot_subsets)
    if request.strip_source_roots:
        all_sources_fields = (*full_snapshots.keys(), *snapshot_subset_requests.keys())
        stripped_snapshots = await MultiGet(
            Get[SourceRootStrippedSources](
                StripSourcesFieldRequest(sources_field, specified_files_snapshot=snapshot)
            )
            for sources_field, snapshot in zip(all_sources_fields, all_snapshots)
        )
        all_snapshots = (stripped_snapshot.snapshot for stripped_snapshot in stripped_snapshots)
    result = await Get[Snapshot](
        DirectoriesToMerge(tuple(snapshot.directory_digest for snapshot in all_snapshots))
    )
    return SourceFiles(result)


def rules():
    return [
        determine_all_source_files,
        determine_specified_source_files,
        RootRule(AllSourceFilesRequest),
        RootRule(SpecifiedSourceFilesRequest),
        *strip_source_roots.rules(),
    ]
