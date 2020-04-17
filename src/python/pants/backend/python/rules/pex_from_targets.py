# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from pants.backend.python.rules.importable_python_sources import ImportablePythonSources
from pants.backend.python.rules.pex import (
    PexInterpreterConstraints,
    PexPlatforms,
    PexRequest,
    PexRequirements,
    TwoStepPexRequest,
)
from pants.backend.python.rules.targets import (
    PythonInterpreterCompatibility,
    PythonRequirementsField,
    PythonRequirementsFileSources,
    PythonSources,
)
from pants.engine.addressable import Addresses
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.rules import RootRule, named_rule, rule
from pants.engine.selectors import Get
from pants.engine.target import Targets, TransitiveTargets
from pants.python.python_setup import PythonSetup
from pants.rules.core.targets import FilesSources, ResourcesSources
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexFromTargetsRequest:
    """Request to create a PEX from the closure of a set of targets."""

    addresses: Addresses
    output_filename: str
    entry_point: Optional[str]
    platforms: PexPlatforms
    additional_args: Tuple[str, ...]
    additional_requirements: Tuple[str, ...]
    include_source_files: bool
    additional_sources: Optional[Digest]
    additional_inputs: Optional[Digest]
    # A human-readable description to use in the UI.  This field doesn't participate
    # in comparison (and therefore hashing), as it doesn't affect the result.
    description: Optional[str] = dataclasses.field(compare=False)

    def __init__(
        self,
        addresses: Addresses,
        *,
        output_filename: str,
        entry_point: Optional[str] = None,
        platforms: PexPlatforms = PexPlatforms(),
        additional_args: Iterable[str] = (),
        additional_requirements: Iterable[str] = (),
        include_source_files: bool = True,
        additional_sources: Optional[Digest] = None,
        additional_inputs: Optional[Digest] = None,
        description: Optional[str] = None
    ) -> None:
        self.addresses = addresses
        self.output_filename = output_filename
        self.entry_point = entry_point
        self.platforms = platforms
        self.additional_args = tuple(additional_args)
        self.additional_requirements = tuple(additional_requirements)
        self.include_source_files = include_source_files
        self.additional_sources = additional_sources
        self.additional_inputs = additional_inputs
        self.description = description


@dataclass(frozen=True)
class TwoStepPexFromTargetsRequest:
    """Request to create a PEX from the closure of a set of targets, in two steps.

    First we create a requirements-only pex. Then we create the full pex on top of that
    requirements pex, instead of having the full pex directly resolve its requirements.

    This allows us to re-use the requirements-only pex when no requirements have changed (which is
    the overwhelmingly common case), thus avoiding spurious re-resolves of the same requirements
    over and over again.
    """

    pex_from_targets_request: PexFromTargetsRequest


@named_rule(desc="Create a PEX from targets")
async def pex_from_targets(request: PexFromTargetsRequest, python_setup: PythonSetup) -> PexRequest:
    transitive_targets = await Get[TransitiveTargets](Addresses, request.addresses)
    all_targets = transitive_targets.closure

    python_targets = []
    resource_targets = []
    python_requirement_fields = []
    for tgt in all_targets:
        if tgt.has_field(PythonSources):
            python_targets.append(tgt)
        if tgt.has_field(PythonRequirementsField):
            python_requirement_fields.append(tgt[PythonRequirementsField])
        # NB: PythonRequirementsFileSources is a subclass of FilesSources. We filter it out so that
        # requirements.txt is not included in the PEX and so that irrelevant changes to it (e.g.
        # whitespace changes) do not invalidate the PEX.
        if tgt.has_field(ResourcesSources) or (
            tgt.has_field(FilesSources) and not tgt.has_field(PythonRequirementsFileSources)
        ):
            resource_targets.append(tgt)

    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (tgt.get(PythonInterpreterCompatibility) for tgt in python_targets), python_setup
    )

    input_digests = []
    if request.additional_sources:
        input_digests.append(request.additional_sources)
    if request.include_source_files:
        prepared_sources = await Get[ImportablePythonSources](
            Targets(python_targets + resource_targets)
        )
        input_digests.append(prepared_sources.snapshot.directory_digest)
    merged_input_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(input_digests)))

    requirements = PexRequirements.create_from_requirement_fields(
        python_requirement_fields, additional_requirements=request.additional_requirements
    )

    return PexRequest(
        output_filename=request.output_filename,
        requirements=requirements,
        interpreter_constraints=interpreter_constraints,
        platforms=request.platforms,
        entry_point=request.entry_point,
        sources=merged_input_digest,
        additional_inputs=request.additional_inputs,
        additional_args=request.additional_args,
        description=request.description,
    )


@rule
async def two_step_pex_from_targets(req: TwoStepPexFromTargetsRequest) -> TwoStepPexRequest:
    pex_request = await Get[PexRequest](PexFromTargetsRequest, req.pex_from_targets_request)
    return TwoStepPexRequest(pex_request=pex_request)


def rules():
    return [
        pex_from_targets,
        two_step_pex_from_targets,
        RootRule(PexFromTargetsRequest),
        RootRule(TwoStepPexFromTargetsRequest),
    ]
