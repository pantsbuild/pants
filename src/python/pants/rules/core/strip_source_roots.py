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
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.source.source_root import NoSourceRootError, SourceRootConfig


@dataclass(frozen=True)
class SourceRootStrippedSources:
  """Wrapper for a snapshot of targets whose source roots have been stripped."""
  snapshot: Snapshot


@dataclass(frozen=True)
class StripSourceRootsRequest:
  """A request to strip source roots for every file in the snapshot.

  The call site must decide whether to allow the snapshot to include multiple source roots or not,
  e.g. the snapshot including `src/python/lib.py` and `src/java/lib.java`. If the snapshot
  is certain to only one have single source root among all the files, then the call site should pass
  a `representative_path` for better performance. If the snapshot is likely to have more than one
  snapshot, the call site should set `support_multiple_source_roots=True`, which has worse
  performance but ensures correctness.
  """
  snapshot: Snapshot
  multiple_source_roots: bool = False
  representative_path: Optional[str] = None

  def __post_init__(self) -> None:
    if self.multiple_source_roots and self.representative_path is not None:
      raise ValueError(
        "You requested `multiple_source_roots=True` but also gave a "
        f"`representative_path` of `{self.representative_path}`. Please only do one of these "
        "things.\n\nIf you expect your snapshot to only have one single source root, then you "
        "should stop setting `multiple_source_roots=True` and keep setting "
        "`representative_path` for better performance.\n\nIf you expect there to be one or more "
        "source roots, keep setting `multiple_source_roots=True` and remove "
        "`representative_path`."
      )
    if not self.multiple_source_roots and self.representative_path is None:
      raise ValueError(
        "You did not give a `representative_path` while using the default value of "
        "`multiple_source_roots=False`. Please either give a `representative_path` value "
        "or set `multiple_source_roots=True`.\n\nIf you expect your snapshot to only have "
        "one single source root, then you should keep using `multiple_source_roots=False` "
        "and set `representative_path` for better performance.\n\nIf you expect there to be one or "
        "more source roots, set `multiple_source_roots=True`."
      )


@rule
async def strip_source_roots_from_snapshot(
  request: StripSourceRootsRequest, source_root_config: SourceRootConfig,
) -> SourceRootStrippedSources:
  """Removes source roots from a snapshot,
  e.g. `src/python/pants/util/strutil.py` -> `pants/util/strutil.py`.
  """
  source_roots_object = source_root_config.get_source_roots()

  def determine_source_root(path: str) -> str:
    source_root = source_roots_object.safe_find_by_path(path)
    if source_root is not None:
      return cast(str, source_root.path)
    if source_root_config.options.unmatched == "fail":
      raise NoSourceRootError(f"Could not find a source root for `{path}`.")
    # Otherwise, create a source root by using the parent directory.
    return PurePath(path).parent.as_posix()

  if not request.multiple_source_roots:
    resulting_digest = await Get[Digest](
      DirectoryWithPrefixToStrip(
        directory_digest=request.snapshot.directory_digest,
        # NB: We are certain that `request.representative_path` is not None due to
        # `StripSourceRootsRequest.__post_init__()`, but MyPy can't infer this.
        prefix=determine_source_root(request.representative_path),  # type: ignore[arg-type]
      )
    )
    resulting_snapshot = await Get[Snapshot](Digest, resulting_digest)
    return SourceRootStrippedSources(snapshot=resulting_snapshot)

  files_grouped_by_source_root = {
    source_root: tuple(files)
    for source_root, files
    in itertools.groupby(request.snapshot.files, key=determine_source_root)
  }
  snapshot_subsets = await MultiGet(
    Get[Snapshot](
      SnapshotSubset(
        directory_digest=request.snapshot.directory_digest,
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
  return SourceRootStrippedSources(resulting_snapshot)


@rule
async def strip_source_roots_from_target(
  hydrated_target: HydratedTarget,
) -> SourceRootStrippedSources:
  """Remove source roots from a target, e.g.
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

  build_file = PurePath(hydrated_target.address.spec_path, "BUILD").as_posix()
  return await Get[SourceRootStrippedSources](
    StripSourceRootsRequest(target_adaptor.sources.snapshot, representative_path=build_file)
  )


def rules():
  return [
    strip_source_roots_from_snapshot,
    strip_source_roots_from_target,
    subsystem_rule(SourceRootConfig),
  ]
