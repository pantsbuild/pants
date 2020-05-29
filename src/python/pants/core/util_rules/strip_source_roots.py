# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Optional, Tuple, Type

from pants.core.target_types import FilesSources
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    Digest,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
    SnapshotSubset,
)
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.target import Sources as SourcesField
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class SourceRootStrippedSources:
    """Wrapper for a snapshot of files whose source roots have been stripped."""

    snapshot: Snapshot
    # source root -> file paths relative to that root.
    # Note that this will not contain entries for files to which the concept of source roots
    # doesn't apply (e.g., the sources of a files(...) target), even when such files are
    # in the snapshot.
    root_to_relfiles: FrozenDict[str, Tuple[str, ...]]

    @classmethod
    def for_single_source_root(
        cls, snapshot: Snapshot, source_root: str
    ) -> "SourceRootStrippedSources":
        return cls(snapshot, FrozenDict({source_root: snapshot.files}))

    def get_file_to_stripped_file_mapping(self) -> FrozenDict[str, str]:
        """Generate a mapping from original path to stripped path."""
        return FrozenDict(
            {
                (os.path.join(root, relpath) if root != "." else relpath): relpath
                for root, relpaths in self.root_to_relfiles.items()
                for relpath in relpaths
            }
        )


@dataclass(frozen=True)
class StripSnapshotRequest:
    """A request to strip source roots for every file in the snapshot.

    The call site may optionally give the field `representative_path` if it is confident that all
    the files in the snapshot will only have one source root. Using `representative_path` results in
    better performance because we only need to find the SourceRoot for a single file rather than
    every file. The `representative_path` cannot be the source root path itself, it must be some
    proper subpath of it.
    """

    snapshot: Snapshot
    representative_path: Optional[str] = None


@frozen_after_init
@dataclass(unsafe_hash=True)
class StripSourcesFieldRequest:
    """A request to strip source roots for every file in a `Sources` field.

    The call site may optionally give a snapshot to `specified_files_snapshot` to only strip a
    subset of the target's `sources`, rather than every `sources` file. This is useful when working
    with precise file arguments.
    """

    sources_field: SourcesField
    for_sources_types: Tuple[Type[SourcesField], ...]
    enable_codegen: bool
    specified_files_snapshot: Optional[Snapshot]

    def __init__(
        self,
        sources_field: SourcesField,
        *,
        for_sources_types: Iterable[Type[SourcesField]] = (SourcesField,),
        enable_codegen: bool = False,
        specified_files_snapshot: Optional[Snapshot] = None,
    ) -> None:
        self.sources_field = sources_field
        self.for_sources_types = tuple(for_sources_types)
        self.enable_codegen = enable_codegen
        self.specified_files_snapshot = specified_files_snapshot


@rule
async def strip_source_roots_from_snapshot(
    request: StripSnapshotRequest,
) -> SourceRootStrippedSources:
    """Removes source roots from a snapshot, e.g. `src/python/pants/util/strutil.py` ->
    `pants/util/strutil.py`."""
    if not request.snapshot.files:
        return SourceRootStrippedSources(request.snapshot, FrozenDict())

    if request.representative_path is not None:
        source_root_obj = await Get[SourceRoot](
            SourceRootRequest, SourceRootRequest.for_file(request.representative_path)
        )
        source_root = source_root_obj.path
        if source_root == ".":
            return SourceRootStrippedSources.for_single_source_root(request.snapshot, source_root)
        resulting_snapshot = await Get[Snapshot](RemovePrefix(request.snapshot.digest, source_root))
        return SourceRootStrippedSources.for_single_source_root(resulting_snapshot, source_root)

    source_roots = await MultiGet(
        Get[SourceRoot](SourceRootRequest, SourceRootRequest.for_file(file))
        for file in request.snapshot.files
    )
    file_to_source_root = dict(zip(request.snapshot.files, source_roots))
    files_grouped_by_source_root = {
        source_root.path: tuple(files)
        for source_root, files in itertools.groupby(
            request.snapshot.files, key=file_to_source_root.__getitem__
        )
    }

    if len(files_grouped_by_source_root) == 1:
        source_root = next(iter(files_grouped_by_source_root.keys()))
        if source_root == ".":
            return SourceRootStrippedSources.for_single_source_root(request.snapshot, source_root)
        resulting_snapshot = await Get[Snapshot](RemovePrefix(request.snapshot.digest, source_root))
        return SourceRootStrippedSources.for_single_source_root(resulting_snapshot, source_root)

    snapshot_subsets = await MultiGet(
        Get[Snapshot](SnapshotSubset(request.snapshot.digest, PathGlobs(files)))
        for files in files_grouped_by_source_root.values()
    )
    resulting_digests = await MultiGet(
        Get[Digest](RemovePrefix(snapshot.digest, source_root))
        for snapshot, source_root in zip(snapshot_subsets, files_grouped_by_source_root.keys())
    )

    resulting_snapshot = await Get[Snapshot](MergeDigests(resulting_digests))
    return SourceRootStrippedSources(
        resulting_snapshot,
        FrozenDict(
            {
                source_root: tuple(file[len(source_root) + 1 :] for file in files)
                for source_root, files in files_grouped_by_source_root.items()
            }
        ),
    )


def representative_path_from_address(address: Address) -> str:
    """Generate a representative path for an address.

    A performance hack, so that we don't need to determine the SourceRoot of every single file
    belonging to a target.
    """
    return PurePath(address.spec_path, "BUILD").as_posix()


@rule
async def strip_source_roots_from_sources_field(
    request: StripSourcesFieldRequest,
) -> SourceRootStrippedSources:
    """Remove source roots from a target, e.g. `src/python/pants/util/strutil.py` ->
    `pants/util/strutil.py`."""
    if request.specified_files_snapshot is not None:
        sources_snapshot = request.specified_files_snapshot
    else:
        hydrated_sources = await Get[HydratedSources](
            HydrateSourcesRequest(
                request.sources_field,
                for_sources_types=request.for_sources_types,
                enable_codegen=request.enable_codegen,
            )
        )
        sources_snapshot = hydrated_sources.snapshot

    if not sources_snapshot.files:
        return SourceRootStrippedSources(EMPTY_SNAPSHOT, FrozenDict())

    # Unlike all other `Sources` subclasses, `FilesSources` (and its subclasses) do not remove
    # their source root. This is so that filesystem APIs (e.g. Python's `open()`) may still access
    # the files as they normally would, with the full path relative to the build root.
    if isinstance(request.sources_field, FilesSources):
        return SourceRootStrippedSources(sources_snapshot, FrozenDict())

    return await Get[SourceRootStrippedSources](
        StripSnapshotRequest(
            sources_snapshot,
            representative_path=representative_path_from_address(request.sources_field.address),
        )
    )


def rules():
    return [
        strip_source_roots_from_snapshot,
        strip_source_roots_from_sources_field,
        RootRule(StripSnapshotRequest),
        RootRule(StripSourcesFieldRequest),
    ]
