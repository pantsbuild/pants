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
class ChrootedPythonSourcesRequest:
  hydrated_targets: HydratedTargets


@rule
async def prepare_chrooted_python_sources(request: ChrootedPythonSourcesRequest) -> Digest:
  source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, target_adaptor)
    for target_adaptor in request.hydrated_targets
  )

  stripped_sources_digests = [stripped_sources.snapshot.directory_digest
                              for stripped_sources in source_root_stripped_sources]
  sources_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(stripped_sources_digests)))
  inits_digest = await Get[InjectedInitDigest](Digest, sources_digest)
  all_input_digests = (sources_digest, inits_digest.directory_digest)
  merged_input_files = await Get[Digest](DirectoriesToMerge(directories=all_input_digests))
  return merged_input_files


def rules():
  return [
    prepare_chrooted_python_sources,
  ]
