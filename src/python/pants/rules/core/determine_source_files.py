# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Tuple, Union, cast

from pants.base.specs import AddressSpec
from pants.engine.fs import DirectoriesToMerge, PathGlobs, Snapshot, SnapshotSubset
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_roots import SourceRootStrippedSources, StripSnapshotRequest
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class SourceFiles:
    """A merged snapshot of the `sources` fields of multiple targets, possibly containing a subset
    of the `sources` when using `SpecifiedSourceFilesRequest` (instead of
    `AllSourceFilesRequest`)."""

    snapshot: Snapshot


@frozen_after_init
@dataclass(unsafe_hash=True)
class SpecifiedSourceFilesRequest:
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


def determine_specified_sources_for_target(
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
async def determine_specified_source_files(request: SpecifiedSourceFilesRequest,) -> SourceFiles:
    """Determine the specified `sources` for targets, possibly finding a subset of the original
    `sources` fields if the user supplied file arguments."""
    full_snapshots = []
    snapshot_subset_requests = []
    for adaptor_with_origin in request.adaptors_with_origins:
        result = determine_specified_sources_for_target(adaptor_with_origin)
        if isinstance(result, Snapshot):
            full_snapshots.append(result)
        else:
            snapshot_subset_requests.append(result)

    snapshot_subsets: Tuple[Snapshot, ...] = ()
    if snapshot_subset_requests:
        snapshot_subsets = await MultiGet(
            Get[Snapshot](SnapshotSubset, request) for request in snapshot_subset_requests
        )

    merged_snapshot = await Get[Snapshot](
        DirectoriesToMerge(
            tuple(snapshot.directory_digest for snapshot in (*full_snapshots, *snapshot_subsets))
        )
    )

    if not request.strip_source_roots:
        return SourceFiles(merged_snapshot)

    # If there is exactly one target in the request, we use a performance optimization for
    # `StripSourceRootsRequest` to pass a `representative_path` so that the rule does not need to
    # determine the source root for every single file, but instead infers it from the
    # `representative_path`. This is not safe when we have multiple targets because every target
    # might have a different source root.
    representative_path = (
        None
        if len(request.adaptors_with_origins) != 1
        else PurePath(
            request.adaptors_with_origins[0].adaptor.address.spec_path, "BUILD"
        ).as_posix()
    )
    stripped = await Get[SourceRootStrippedSources](
        StripSnapshotRequest(merged_snapshot, representative_path=representative_path)
    )
    return SourceFiles(stripped.snapshot)


def rules():
    return [determine_specified_source_files, RootRule(SpecifiedSourceFilesRequest)]
