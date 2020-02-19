# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.fs import (
  EMPTY_DIRECTORY_DIGEST,
  Digest,
  DirectoriesToMerge,
  FileContent,
  InputFilesContent,
  Snapshot,
)
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.python.pex_build_util import identify_missing_init_files
from pants.rules.core.strip_source_roots import SourceRootStrippedSources


@dataclass(frozen=True)
class ChrootedPythonSources:
  snapshot: Snapshot


@rule
async def prepare_chrooted_python_sources(
  hydrated_targets: HydratedTargets,
) -> ChrootedPythonSources:
  """Prepares Python sources by stripping the source root and injecting missing __init__.py files.

  NB: This is useful for Pytest or ./pants run, but not every Python rule will need this.
  For example, autoformatters like Black do not need to understand relative imports or
  execute the code, so they can safely operate on the original source files without
  stripping source roots.
  """
  source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, hydrated_target)
    for hydrated_target in hydrated_targets
  )
  sources_snapshot = await Get[Snapshot](
    DirectoriesToMerge(
      directories=tuple(
        stripped_sources.snapshot.directory_digest
        for stripped_sources in source_root_stripped_sources
      )
    )
  )

  missing_init_files = sorted(identify_missing_init_files(sources_snapshot.files))
  inits_digest = EMPTY_DIRECTORY_DIGEST
  if missing_init_files:
    inits_digest = await Get[Digest](
      InputFilesContent(FileContent(path=fp, content=b"") for fp in missing_init_files)
    )

  result = await Get[Snapshot](
    DirectoriesToMerge(directories=(sources_snapshot.directory_digest, inits_digest))
  )
  return ChrootedPythonSources(result)


def rules():
  return [prepare_chrooted_python_sources]
