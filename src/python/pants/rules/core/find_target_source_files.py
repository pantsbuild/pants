# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath

from pants.base.specs import FilesystemResolvedSpec
from pants.engine.fs import PathGlobs, Snapshot, SnapshotSubset
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.rules.core.strip_source_roots import SourceRootStrippedSources, StripSnapshotRequest


@dataclass(frozen=True)
class FindTargetSourceFilesRequest:
    adaptor_with_origin: TargetAdaptorWithOrigin
    strip_source_roots: bool = False


# NB: This wrapper class is needed to avoid graph ambiguity.
@dataclass(frozen=True)
class TargetSourceFiles:
    snapshot: Snapshot


@rule
async def find_target_source_files(request: FindTargetSourceFilesRequest) -> TargetSourceFiles:
    """Find the `sources` for a target, possibly finding a subset of the original `sources` field if
    the user supplied file arguments."""
    adaptor = request.adaptor_with_origin.adaptor
    origin = request.adaptor_with_origin.origin
    resulting_snapshot = adaptor.sources.snapshot
    if isinstance(origin, FilesystemResolvedSpec):
        # NB: we ensure that `precise_files_specified` is a subset of the original target's `sources`.
        # It's possible when given a glob filesystem spec that the spec will have resolved files not
        # belonging to this target - those must be filtered out.
        precise_files_specified = set(resulting_snapshot.files).intersection(origin.resolved_files)
        resulting_snapshot = await Get[Snapshot](
            SnapshotSubset(
                directory_digest=resulting_snapshot.directory_digest,
                globs=PathGlobs(sorted(precise_files_specified)),
            )
        )
    if not request.strip_source_roots:
        return TargetSourceFiles(resulting_snapshot)
    stripped = await Get[SourceRootStrippedSources](
        StripSnapshotRequest(
            resulting_snapshot,
            # TODO: simply pass `address.spec_path` once `--source-unmatched` is removed.
            representative_path=PurePath(adaptor.address.spec_path, "BUILD").as_posix(),
        )
    )
    return TargetSourceFiles(stripped.snapshot)


def rules():
    return [find_target_source_files, RootRule(FindTargetSourceFilesRequest)]
