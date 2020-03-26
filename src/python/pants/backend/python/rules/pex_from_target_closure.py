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
from pants.engine.addressable import Addresses
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.legacy.structs import FilesAdaptor, PythonTargetAdaptor, ResourcesAdaptor
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.python.python_setup import PythonSetup


@dataclass(frozen=True)
class CreatePexFromTargetClosure:
    """Represents a request to create a PEX from the closure of a set of targets."""

    addresses: Addresses
    output_filename: str
    entry_point: Optional[str] = None
    additional_requirements: Tuple[str, ...] = ()
    include_source_files: bool = True
    additional_args: Tuple[str, ...] = ()
    additional_input_files: Optional[Digest] = None


@rule(name="Create PEX from targets")
async def create_pex_from_target_closure(
    request: CreatePexFromTargetClosure, python_setup: PythonSetup
) -> CreatePex:
    transitive_hydrated_targets = await Get[TransitiveHydratedTargets](Addresses, request.addresses)
    all_targets = transitive_hydrated_targets.closure

    # TODO: Replace this with appropriate target API logic.
    python_targets = [t for t in all_targets if isinstance(t.adaptor, PythonTargetAdaptor)]
    resource_targets = [
        t for t in all_targets if isinstance(t.adaptor, (FilesAdaptor, ResourcesAdaptor))
    ]

    all_target_adaptors = [t.adaptor for t in all_targets]

    interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
        adaptors=all_target_adaptors, python_setup=python_setup
    )

    input_digests = []
    if request.additional_input_files:
        input_digests.append(request.additional_input_files)
    if request.include_source_files:
        chrooted_sources = await Get[ChrootedPythonSources](
            HydratedTargets(python_targets + resource_targets)
        )
        input_digests.append(chrooted_sources.snapshot.directory_digest)
    merged_input_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(input_digests)))
    requirements = PexRequirements.create_from_adaptors(
        adaptors=all_target_adaptors, additional_requirements=request.additional_requirements
    )

    return CreatePex(
        output_filename=request.output_filename,
        requirements=requirements,
        interpreter_constraints=interpreter_constraints,
        entry_point=request.entry_point,
        input_files_digest=merged_input_digest,
        additional_args=request.additional_args,
    )


def rules():
    return [
        create_pex_from_target_closure,
    ]
