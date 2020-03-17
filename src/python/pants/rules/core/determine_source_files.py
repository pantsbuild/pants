# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, Tuple, Union, cast

from pants.base.specs import AddressSpec
from pants.engine.fs import DirectoriesToMerge, PathGlobs, Snapshot, SnapshotSubset
from pants.engine.legacy.structs import TargetAdaptor, TargetAdaptorWithOrigin
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core import strip_source_roots
from pants.rules.core.strip_source_roots import (
    LegacySourceRootStrippedSources,
    LegacyStripTargetRequest,
)
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class SourceFiles:
    """A merged snapshot of the `sources` fields of multiple targets, possibly containing a subset
    of the `sources` when using `LegacySpecifiedSourceFilesRequest` (instead of
    `LegacyAllSourceFilesRequest`)."""

    snapshot: Snapshot


@frozen_after_init
@dataclass(unsafe_hash=True)
class LegacyAllSourceFilesRequest:
    adaptors: Tuple[TargetAdaptor, ...]
    strip_source_roots: bool = False

    def __init__(
        self, adaptors: Iterable[TargetAdaptor], *, strip_source_roots: bool = False
    ) -> None:
        self.adaptors = tuple(adaptors)
        self.strip_source_roots = strip_source_roots


@frozen_after_init
@dataclass(unsafe_hash=True)
class LegacySpecifiedSourceFilesRequest:
    adaptors_with_origins: Tuple[TargetAdaptorWithOrigin, ...]
    strip_source_roots: bool = False

    def __init__(
        self,
        adaptors_with_origins: Iterable[TargetAdaptorWithOrigin],
        *,
        strip_source_roots: bool = False
    ) -> None:
        self.adaptors_with_origins = tuple(adaptors_with_origins)
        self.strip_source_roots = strip_source_roots


@rule
async def legacy_determine_all_source_files(request: LegacyAllSourceFilesRequest) -> SourceFiles:
    """Merge all the `sources` for targets into one snapshot."""
    if request.strip_source_roots:
        stripped_snapshots = await MultiGet(
            Get[LegacySourceRootStrippedSources](LegacyStripTargetRequest(adaptor))
            for adaptor in request.adaptors
        )
        input_snapshots = (stripped_snapshot.snapshot for stripped_snapshot in stripped_snapshots)
    else:
        input_snapshots = (
            adaptor.sources.snapshot for adaptor in request.adaptors if adaptor.has_sources()
        )
    result = await Get[Snapshot](
        DirectoriesToMerge(tuple(snapshot.directory_digest for snapshot in input_snapshots))
    )
    return SourceFiles(result)


def legacy_determine_specified_sources_for_target(
    adaptor_with_origin: TargetAdaptorWithOrigin,
) -> Union[Snapshot, SnapshotSubset]:
    adaptor = adaptor_with_origin.adaptor
    origin = adaptor_with_origin.origin
    sources_snapshot = cast(Snapshot, adaptor.sources.snapshot)
    # AddressSpecs simply use the entire `sources` field.
    if isinstance(origin, AddressSpec):
        return sources_snapshot
    # NB: we ensure that `precise_files_specified` is a subset of the original target's
    # `sources`. It's possible when given a glob filesystem spec that the spec will have
    # resolved files not belonging to this target - those must be filtered out.
    precise_files_specified = set(sources_snapshot.files).intersection(origin.resolved_files)
    return SnapshotSubset(
        directory_digest=sources_snapshot.directory_digest,
        globs=PathGlobs(sorted(precise_files_specified)),
    )


@rule
async def legacy_determine_specified_source_files(
    request: LegacySpecifiedSourceFilesRequest,
) -> SourceFiles:
    """Determine the specified `sources` for targets, possibly finding a subset of the original
    `sources` fields if the user supplied file arguments."""
    full_snapshots = {}
    snapshot_subset_requests = {}
    for adaptor_with_origin in request.adaptors_with_origins:
        adaptor = adaptor_with_origin.adaptor
        if not adaptor.has_sources():
            continue
        result = legacy_determine_specified_sources_for_target(adaptor_with_origin)
        if isinstance(result, Snapshot):
            full_snapshots[adaptor] = result
        else:
            snapshot_subset_requests[adaptor] = result

    snapshot_subsets: Tuple[Snapshot, ...] = ()
    if snapshot_subset_requests:
        snapshot_subsets = await MultiGet(
            Get[Snapshot](SnapshotSubset, request) for request in snapshot_subset_requests.values()
        )

    all_snapshots: Iterable[Snapshot] = (*full_snapshots.values(), *snapshot_subsets)
    if request.strip_source_roots:
        all_adaptors = (*full_snapshots.keys(), *snapshot_subset_requests.keys())
        stripped_snapshots = await MultiGet(
            Get[LegacySourceRootStrippedSources](
                LegacyStripTargetRequest(adaptor, specified_files_snapshot=snapshot)
            )
            for adaptor, snapshot in zip(all_adaptors, all_snapshots)
        )
        all_snapshots = (stripped_snapshot.snapshot for stripped_snapshot in stripped_snapshots)
    result = await Get[Snapshot](
        DirectoriesToMerge(tuple(snapshot.directory_digest for snapshot in all_snapshots))
    )
    return SourceFiles(result)


def rules():
    return [
        legacy_determine_all_source_files,
        legacy_determine_specified_source_files,
        *strip_source_roots.rules(),
        RootRule(LegacyAllSourceFilesRequest),
        RootRule(LegacySpecifiedSourceFilesRequest),
    ]
