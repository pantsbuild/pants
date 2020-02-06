# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.rules.prepare_chrooted_python_sources import ChrootedPythonSources
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.addressable import Addresses
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.rules import rule
from pants.engine.selectors import Get


@dataclass(frozen=True)
class CreatePexFromTargetClosure:
  """Represents a request to create a PEX from the closure of a set of targets."""
  addresses: Addresses
  output_filename: str
  entry_point: Optional[str] = None
  additional_requirements: Tuple[str, ...] = ()
  include_source_files: bool = True
  additional_args: Tuple[str, ...] = ()


@rule(name="Create PEX from targets")
async def create_pex_from_target_closure(request: CreatePexFromTargetClosure,
                                         python_setup: PythonSetup) -> Pex:
  transitive_hydrated_targets = await Get[TransitiveHydratedTargets](Addresses, request.addresses)
  all_targets = transitive_hydrated_targets.closure
  all_target_adaptors = [t.adaptor for t in all_targets]

  interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
    adaptors=tuple(all_target_adaptors),
    python_setup=python_setup
  )

  if request.include_source_files:
    chrooted_sources = await Get[ChrootedPythonSources](HydratedTargets(all_targets))

  requirements = PexRequirements.create_from_adaptors(
    adaptors=all_target_adaptors,
    additional_requirements=request.additional_requirements
  )

  create_pex_request = CreatePex(
    output_filename=request.output_filename,
    requirements=requirements,
    interpreter_constraints=interpreter_constraints,
    entry_point=request.entry_point,
    input_files_digest=chrooted_sources.digest if request.include_source_files else None,
    additional_args=request.additional_args,
  )

  pex = await Get[Pex](CreatePex, create_pex_request)
  return pex


def rules():
  return [
    create_pex_from_target_closure,
  ]
