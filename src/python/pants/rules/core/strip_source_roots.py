# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional, cast

from pants.build_graph.files import Files
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToStrip,
    PathGlobs,
    Snapshot,
    SnapshotSubset,
)
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.rules import RootRule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.source.source_root import NoSourceRootError, SourceRootConfig


@dataclass(frozen=True)
class SourceRootStrippedSources:
    """Wrapper for a snapshot of targets whose source roots have been stripped."""

    snapshot: Snapshot


@dataclass(frozen=True)
class StripSnapshotRequest:
    """A request to strip source roots for every file in the snapshot.

    The call site may optionally give the field `representative_path` if it is confident that all
    the files in the snapshot will only have one source root. Using `representative_path` results in
    better performance because we only need to call `SourceRoots.find_by_path()` on one single file
    rather than every file.
    """

    snapshot: Snapshot
    representative_path: Optional[str] = None


@dataclass(frozen=True)
class StripTargetRequest:
    """A request to strip source roots for every file in a target's `sources` field.

    The call site may optionally give a snapshot to `specified_files_snapshot` to only strip a
    subset of the target's `sources`, rather than every `sources` file. This is useful when working
    with precise file arguments.
    """

    adaptor: TargetAdaptor
    specified_files_snapshot: Optional[Snapshot] = None


@rule
async def strip_source_roots_from_snapshot(
    request: StripSnapshotRequest, source_root_config: SourceRootConfig,
) -> SourceRootStrippedSources:
    """Removes source roots from a snapshot, e.g. `src/python/pants/util/strutil.py` ->
    `pants/util/strutil.py`."""
    source_roots_object = source_root_config.get_source_roots()

    def determine_source_root(path: str) -> str:
        source_root = source_roots_object.safe_find_by_path(path)
        if source_root is not None:
            return cast(str, source_root.path)
        if source_root_config.options.unmatched == "fail":
            raise NoSourceRootError(f"Could not find a source root for `{path}`.")
        # Otherwise, create a source root by using the parent directory.
        return PurePath(path).parent.as_posix()

    if request.representative_path is not None:
        resulting_digest = await Get[Digest](
            DirectoryWithPrefixToStrip(
                directory_digest=request.snapshot.directory_digest,
                prefix=determine_source_root(request.representative_path),
            )
        )
        resulting_snapshot = await Get[Snapshot](Digest, resulting_digest)
        return SourceRootStrippedSources(snapshot=resulting_snapshot)

    files_grouped_by_source_root = {
        source_root: tuple(files)
        for source_root, files in itertools.groupby(
            request.snapshot.files, key=determine_source_root
        )
    }
    snapshot_subsets = await MultiGet(
        Get[Snapshot](
            SnapshotSubset(
                directory_digest=request.snapshot.directory_digest, globs=PathGlobs(files),
            )
        )
        for files in files_grouped_by_source_root.values()
    )
    resulting_digests = await MultiGet(
        Get[Digest](
            DirectoryWithPrefixToStrip(
                directory_digest=snapshot.directory_digest, prefix=source_root
            )
        )
        for snapshot, source_root in zip(snapshot_subsets, files_grouped_by_source_root.keys())
    )

    merged_result = await Get[Digest](DirectoriesToMerge(resulting_digests))
    resulting_snapshot = await Get[Snapshot](Digest, merged_result)
    return SourceRootStrippedSources(resulting_snapshot)


@rule
async def strip_source_roots_from_target(request: StripTargetRequest,) -> SourceRootStrippedSources:
    """Remove source roots from a target, e.g. `src/python/pants/util/strutil.py` ->
    `pants/util/strutil.py`."""
    target_adaptor = request.adaptor

    if not target_adaptor.has_sources():
        return SourceRootStrippedSources(snapshot=EMPTY_SNAPSHOT)

    sources_snapshot = request.specified_files_snapshot or target_adaptor.sources.snapshot

    # Loose `Files`, as opposed to `Resources` or `Target`s, have no (implied) package
    # structure and so we do not remove their source root like we normally do, so that filesystem
    # APIs may still access the files. See pex_build_util.py's `_create_source_dumper`.
    if target_adaptor.type_alias == Files.alias():
        return SourceRootStrippedSources(sources_snapshot)

    # NB: We generate a synthetic representative_path for the target as a performance hack so that
    # we don't need to call SourceRoots.find_by_path() on every single file belonging to the
    # target's `sources`.
    representative_path = PurePath(target_adaptor.address.spec_path, "BUILD").as_posix()
    return await Get[SourceRootStrippedSources](
        StripSnapshotRequest(sources_snapshot, representative_path=representative_path)
    )


def rules():
    return [
        strip_source_roots_from_snapshot,
        strip_source_roots_from_target,
        subsystem_rule(SourceRootConfig),
        RootRule(StripTargetRequest),
        RootRule(StripSnapshotRequest),
    ]
