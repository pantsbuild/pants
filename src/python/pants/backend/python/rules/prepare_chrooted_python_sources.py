# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources


@dataclass(frozen=True)
class ChrootedPythonSources:
  digest: Digest


@rule
async def prepare_chrooted_python_sources(hydrated_targets: HydratedTargets) -> ChrootedPythonSources:
  """Prepares Python sources by stripping the source root and injecting missing init.py files.

  NB: This is useful for Pytest or ./pants run, but not every Python rule will need this.
  For example, autoformatters like Black do not need to understand relative imports or
  execute the code, so they can safely operate on the original source files without
  stripping source roots.
  """

  source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, hydrated_target)
    for hydrated_target in hydrated_targets
  )

  sources_digest = await Get[Digest](DirectoriesToMerge(
    directories=tuple(
      stripped_sources.snapshot.directory_digest for stripped_sources in source_root_stripped_sources
    )
  ))
  inits_digest = await Get[InjectedInitDigest](Digest, sources_digest)
  sources_digest = await Get[Digest](DirectoriesToMerge(
    directories=(sources_digest, inits_digest.directory_digest)
  ))
  return ChrootedPythonSources(digest=sources_digest)


def rules():
  return [
    prepare_chrooted_python_sources,
  ]
