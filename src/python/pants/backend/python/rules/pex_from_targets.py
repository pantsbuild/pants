# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.rules.importable_python_sources import ImportablePythonSources
from pants.backend.python.rules.pex import PexInterpreterConstraints, PexRequest, PexRequirements
from pants.backend.python.rules.targets import (
    PythonInterpreterCompatibility,
    PythonRequirementsField,
    PythonRequirementsFileSources,
    PythonSources,
)
from pants.engine.addressable import Addresses
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.legacy.structs import FilesAdaptor, PythonTargetAdaptor, ResourcesAdaptor
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.engine.target import Targets, TransitiveTargets
from pants.python.python_setup import PythonSetup
from pants.rules.core.targets import FilesSources, ResourcesSources


@dataclass(frozen=True)
class PexFromTargetsRequest:
    """Request to create a PEX from the closure of a set of targets."""

    addresses: Addresses
    output_filename: str
    entry_point: Optional[str] = None
    additional_requirements: Tuple[str, ...] = ()
    include_source_files: bool = True
    additional_args: Tuple[str, ...] = ()
    additional_input_files: Optional[Digest] = None


@rule(name="Create a PEX from targets")
async def pex_from_targets(request: PexFromTargetsRequest, python_setup: PythonSetup) -> PexRequest:
    transitive_targets = await Get[TransitiveTargets](Addresses, request.addresses)
    all_targets = transitive_targets.closure

    python_targets = []
    python_requirement_targets = []
    resource_targets = []
    for tgt in all_targets:
        if tgt.has_field(PythonSources):
            python_targets.append(tgt)
        if tgt.has_field(PythonRequirementsField):
            python_requirement_targets.append(tgt)
        # NB: PythonRequirementsFileSources is a subclass of FilesSources. We filter it out so that
        # requirements.txt is not included in the PEX.
        if tgt.has_field(ResourcesSources) or (
            tgt.has_field(FilesSources) and not tgt.has_field(PythonRequirementsFileSources)
        ):
            resource_targets.append(tgt)

    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (tgt.get(PythonInterpreterCompatibility) for tgt in python_targets), python_setup
    )

    input_digests = []
    if request.additional_input_files:
        input_digests.append(request.additional_input_files)
    if request.include_source_files:
        prepared_sources = await Get[ImportablePythonSources](
            Targets(python_targets + resource_targets)
        )
        input_digests.append(prepared_sources.snapshot.directory_digest)
    merged_input_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(input_digests)))

    requirements = PexRequirements.create_from_requirement_fields(
        (tgt[PythonRequirementsField] for tgt in python_requirement_targets),
        additional_requirements=request.additional_requirements,
    )

    return PexRequest(
        output_filename=request.output_filename,
        requirements=requirements,
        interpreter_constraints=interpreter_constraints,
        entry_point=request.entry_point,
        input_files_digest=merged_input_digest,
        additional_args=request.additional_args,
    )


@dataclass(frozen=True)
class LegacyPexFromTargetsRequest:
    """Represents a request to create a PEX from the closure of a set of targets."""

    addresses: Addresses
    output_filename: str
    entry_point: Optional[str] = None
    additional_requirements: Tuple[str, ...] = ()
    include_source_files: bool = True
    additional_args: Tuple[str, ...] = ()
    additional_input_files: Optional[Digest] = None


@rule(name="Create PEX from targets")
async def legacy_pex_from_targets(
    request: LegacyPexFromTargetsRequest, python_setup: PythonSetup
) -> PexRequest:
    transitive_hydrated_targets = await Get[TransitiveHydratedTargets](Addresses, request.addresses)
    all_targets = transitive_hydrated_targets.closure

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
        prepared_sources = await Get[ImportablePythonSources](
            HydratedTargets(python_targets + resource_targets)
        )
        input_digests.append(prepared_sources.snapshot.directory_digest)
    merged_input_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(input_digests)))
    requirements = PexRequirements.create_from_adaptors(
        adaptors=all_target_adaptors, additional_requirements=request.additional_requirements
    )

    return PexRequest(
        output_filename=request.output_filename,
        requirements=requirements,
        interpreter_constraints=interpreter_constraints,
        entry_point=request.entry_point,
        input_files_digest=merged_input_digest,
        additional_args=request.additional_args,
    )


def rules():
    return [pex_from_targets, legacy_pex_from_targets]
