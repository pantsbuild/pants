# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass

from pants.core.util_rules.source_files import SourceFiles
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, RemovePrefix, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesPaths
from pants.source.source_root import (
    SourceRoot,
    SourceRootRequest,
    SourceRootsRequest,
    SourceRootsResult,
)
from pants.source.source_root import rules as source_root_rules
from pants.util.dirutil import fast_relpath


@dataclass(frozen=True)
class StrippedSourceFiles:
    """Wrapper for a snapshot of files whose source roots have been stripped.

    Use via `Get(StrippedSourceFiles, SourceFilesRequest([tgt.get(SourcesField)])`.
    """

    snapshot: Snapshot


async def _stripped_snapshot_by_source_roots(
    source_roots_result: SourceRootsResult, snapshot: Snapshot
) -> Snapshot:
    source_roots_to_files = defaultdict(set)
    for f, root in source_roots_result.path_to_root.items():
        source_roots_to_files[root.path].add(str(f))

    if len(source_roots_to_files) == 1:
        source_root = next(iter(source_roots_to_files.keys()))
        if source_root == ".":
            resulting_snapshot = snapshot
        else:
            resulting_snapshot = await Get(Snapshot, RemovePrefix(snapshot.digest, source_root))
    else:
        digest_subsets = await MultiGet(
            Get(Digest, DigestSubset(snapshot.digest, PathGlobs(files)))
            for files in source_roots_to_files.values()
        )
        resulting_digests = await MultiGet(
            Get(Digest, RemovePrefix(digest, source_root))
            for digest, source_root in zip(digest_subsets, source_roots_to_files.keys())
        )
        resulting_snapshot = await Get(Snapshot, MergeDigests(resulting_digests))

    return resulting_snapshot


@rule
async def strip_source_roots(source_files: SourceFiles) -> StrippedSourceFiles:
    """Removes source roots from a snapshot.

    E.g. `src/python/pants/util/strutil.py` -> `pants/util/strutil.py`.
    """
    if not source_files.snapshot.files:
        return StrippedSourceFiles(source_files.snapshot)

    if source_files.unrooted_files:
        rooted_files = set(source_files.snapshot.files) - set(source_files.unrooted_files)
        rooted_files_snapshot = await Get(
            Snapshot, DigestSubset(source_files.snapshot.digest, PathGlobs(rooted_files))
        )
    else:
        rooted_files_snapshot = source_files.snapshot

    source_roots_result = await Get(
        SourceRootsResult,
        SourceRootsRequest,
        SourceRootsRequest.for_files(rooted_files_snapshot.files),
    )

    resulting_snapshot = await _stripped_snapshot_by_source_roots(
        source_roots_result, rooted_files_snapshot
    )

    # Add the unrooted files back in.
    if source_files.unrooted_files:
        unrooted_files_digest = await Get(
            Digest,
            DigestSubset(source_files.snapshot.digest, PathGlobs(source_files.unrooted_files)),
        )
        resulting_snapshot = await Get(
            Snapshot, MergeDigests((resulting_snapshot.digest, unrooted_files_digest))
        )

    return StrippedSourceFiles(resulting_snapshot)


@dataclass(frozen=True)
class StrippedFileName:
    value: str


@dataclass(frozen=True)
class StrippedFileNameRequest(EngineAwareParameter):
    file_path: str

    def debug_hint(self) -> str:
        return self.file_path


@rule
async def strip_file_name(request: StrippedFileNameRequest) -> StrippedFileName:
    source_root = await Get(
        SourceRoot, SourceRootRequest, SourceRootRequest.for_file(request.file_path)
    )
    return StrippedFileName(
        request.file_path
        if source_root.path == "."
        else fast_relpath(request.file_path, source_root.path)
    )


class StrippedSourceFileNames(Collection[str]):
    """The file names from a target's `sources` field, with source roots stripped.

    Use via `Get(StrippedSourceFileNames, SourcePathsRequest(tgt.get(SourcesField))`.
    """


@rule
async def strip_sources_paths(sources_paths: SourcesPaths) -> StrippedSourceFileNames:
    if not sources_paths.files:
        return StrippedSourceFileNames()
    source_root = await Get(
        SourceRoot, SourceRootRequest, SourceRootRequest.for_file(sources_paths.files[0])
    )
    if source_root.path == ".":
        return StrippedSourceFileNames(sources_paths.files)
    return StrippedSourceFileNames(fast_relpath(f, source_root.path) for f in sources_paths.files)


def rules():
    return (*collect_rules(), *source_root_rules(), *source_files_rules())
