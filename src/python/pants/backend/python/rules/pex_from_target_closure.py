# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources


@dataclass(frozen=True)
class CreatePexFromTargetClosure:
  """Represents a request to create a PEX from the closure of a set of targets."""
  build_file_addresses: BuildFileAddresses
  output_filename: str
  entry_point: Optional[str] = None


@rule(name="Create PEX from targets")
async def create_pex_from_target_closure(request: CreatePexFromTargetClosure,
                                         python_setup: PythonSetup) -> Pex:
  transitive_hydrated_targets = await Get[TransitiveHydratedTargets](BuildFileAddresses,
                                                                     request.build_file_addresses)
  all_targets = transitive_hydrated_targets.closure
  all_target_adaptors = [t.adaptor for t in all_targets]

  interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
    adaptors=tuple(all_targets),
    python_setup=python_setup
  )

  source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, target_adaptor)
    for target_adaptor in all_targets
  )

  stripped_sources_digests = [stripped_sources.snapshot.directory_digest
                              for stripped_sources in source_root_stripped_sources]
  sources_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(stripped_sources_digests)))
  inits_digest = await Get[InjectedInitDigest](Digest, sources_digest)
  all_input_digests = [sources_digest, inits_digest.directory_digest]
  merged_input_files = await Get[Digest](DirectoriesToMerge,
                                         DirectoriesToMerge(directories=tuple(all_input_digests)))
  requirements = PexRequirements.create_from_adaptors(all_target_adaptors)

  create_pex_request = CreatePex(
    output_filename=request.output_filename,
    requirements=requirements,
    interpreter_constraints=interpreter_constraints,
    entry_point=request.entry_point,
    input_files_digest=merged_input_files,
  )

  pex = await Get[Pex](CreatePex, create_pex_request)
  return pex


def rules():
  return [
    create_pex_from_target_closure,
  ]
