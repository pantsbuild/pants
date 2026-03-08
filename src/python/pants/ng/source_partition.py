# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.collection import Collection
from pants.engine.fs import GlobExpansionConjunction, PathGlobs
from pants.engine.internals.native_engine import (
    Digest,
    PyNgOptions,
    PyNgOptionsReader,
    PyNgSourcePartition,
)
from pants.engine.internals.session import SessionValues
from pants.engine.intrinsics import path_globs_to_digest, path_globs_to_paths
from pants.engine.rules import Rule, _uncacheable_rule, collect_rules, implicitly, rule
from pants.source.source_root import SourceRoot, SourceRootsRequest, get_source_roots
from pants.util.memo import memoized_property


@dataclass(frozen=True)
class SourcePaths:
    """A set of sources, under a single source root."""

    paths: tuple[Path, ...]
    source_root: SourceRoot

    def path_strs(self) -> tuple[str, ...]:
        return tuple(str(path) for path in self.paths)

    def commondir(self) -> str:
        ret = os.path.commonpath(self.paths)
        if os.path.isfile(ret):
            ret = os.path.dirname(ret)
        return ret

    def filter_by_suffixes(self, suffixes: tuple[str, ...]) -> SourcePaths:
        suffixes_set = set(suffixes)
        return SourcePaths(
            tuple(path for path in self.paths if path.suffix in suffixes_set),
            self.source_root,
        )


@dataclass(frozen=True)
class SourceDigest:
    digest: Digest


@rule
async def source_paths_to_digest(source_paths: SourcePaths) -> SourceDigest:
    source_digest = await path_globs_to_digest(
        PathGlobs(
            source_paths.path_strs(),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            conjunction=GlobExpansionConjunction.all_match,
            description_of_origin="Input source paths",
        )
    )
    return SourceDigest(source_digest)


@dataclass(frozen=True)
class SourcePartition:
    """Access to source files and the config that goes with them."""

    _native_partition: PyNgSourcePartition
    _source_root: SourceRoot

    @memoized_property
    def source_paths(self) -> SourcePaths:
        return SourcePaths(
            tuple(Path(p) for p in self._native_partition.paths()), self._source_root
        )

    @memoized_property
    def options_reader(self) -> PyNgOptionsReader:
        return self._native_partition.options_reader()


class SourcePartitions(Collection[SourcePartition]):
    pass


# Uncacheable because we must get the most recent session value on each run.
@_uncacheable_rule
async def get_ng_options(session_values: SessionValues) -> PyNgOptions:
    return session_values[PyNgOptions]


# Uncacheable because we must recompute on each run.
@_uncacheable_rule
async def partition_sources(path_globs: PathGlobs) -> SourcePartitions:
    options = await get_ng_options(**implicitly())
    paths = await path_globs_to_paths(path_globs)
    # First partition by source root.
    source_roots = await get_source_roots(SourceRootsRequest.for_files(paths.files))
    root_to_paths = source_roots.root_to_paths()
    partitions: list[SourcePartition] = []
    for source_root, paths_in_partition in root_to_paths.items():
        # Then subpartition each of those by config.
        partitions.extend(
            SourcePartition(native_part, source_root)
            for native_part in options.partition_sources(
                tuple(str(path) for path in paths_in_partition)
            )
        )
    return SourcePartitions(tuple(partitions))


@rule
async def get_source_paths(partition: SourcePartition) -> SourcePaths:
    return partition.source_paths


def rules() -> tuple[Rule, ...]:
    return (*collect_rules(),)
