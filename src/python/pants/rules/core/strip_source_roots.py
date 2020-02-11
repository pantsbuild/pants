# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from itertools import groupby
from pathlib import PurePath
from typing import cast

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
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.source.source_root import NoSourceRootError, SourceRootConfig


@dataclass(frozen=True)
class SourceRootStrippedSources:
  """Wrapper for a snapshot of targets whose source roots have been stripped."""
  snapshot: Snapshot


@dataclass(frozen=True)
class SnapshotToStrip:
  """A wrapper around Snapshot to remove graph ambiguity."""
  snapshot: Snapshot


@rule
async def strip_source_roots_from_snapshot(
  wrapped_snapshot: SnapshotToStrip, source_root_config: SourceRootConfig,
) -> SourceRootStrippedSources:
  """Removes source roots from a snapshot,
  e.g. `src/python/pants/util/strutil.py` -> `pants/util/strutil.py`.
  """
  source_roots_object = source_root_config.get_source_roots()

  def find_source_root(fp: str) -> str:
    source_root = source_roots_object.safe_find_by_path(fp)
    if source_root is not None:
      return cast(str, source_root.path)
    if source_root_config.options.unmatched == "fail":
      raise NoSourceRootError(f"Could not find a source root for `{fp}`.")
    # Otherwise, create a source root by using the parent directory.
    return PurePath(fp).parent.as_posix()

  files_grouped_by_source_root = {
    source_root: tuple(files)
    for source_root, files
    in groupby(wrapped_snapshot.snapshot.files, key=find_source_root)
  }
  snapshot_subsets = await MultiGet(
    Get[Snapshot](
      SnapshotSubset(
        directory_digest=wrapped_snapshot.snapshot.directory_digest,
        globs=PathGlobs(files),
      )
    )
    for files in files_grouped_by_source_root.values()
  )
  resulting_digests = await MultiGet(
    Get[Digest](
      DirectoryWithPrefixToStrip(directory_digest=snapshot.directory_digest, prefix=source_root)
    )
    for snapshot, source_root in zip(snapshot_subsets, files_grouped_by_source_root.keys())
  )

  merged_result = await Get[Digest](DirectoriesToMerge(resulting_digests))
  resulting_snapshot = await Get[Snapshot](Digest, merged_result)
  return SourceRootStrippedSources(snapshot=resulting_snapshot)


@rule
async def strip_source_roots_from_target(
  hydrated_target: HydratedTarget,
) -> SourceRootStrippedSources:
  """Remove source roots from a target (depending upon the target type), e.g.
  `src/python/pants/util/strutil.py` -> `pants/util/strutil.py`.
  """
  target_adaptor = hydrated_target.adaptor

  # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of raising to
  # simplify the hasattr() checks here!
  if not hasattr(target_adaptor, 'sources'):
    return SourceRootStrippedSources(snapshot=EMPTY_SNAPSHOT)

  # Loose `Files`, as opposed to `Resources` or `Target`s, have no (implied) package
  # structure and so we do not remove their source root like we normally do, so that filesystem
  # APIs may still access the files. See pex_build_util.py's `_create_source_dumper`.
  if target_adaptor.type_alias == Files.alias():
    return SourceRootStrippedSources(snapshot=target_adaptor.sources.snapshot)

  return await Get[SourceRootStrippedSources](SnapshotToStrip(target_adaptor.sources.snapshot))


def rules():
  return [
    strip_source_roots_from_snapshot,
    strip_source_roots_from_target,
    subsystem_rule(SourceRootConfig),
  ]
