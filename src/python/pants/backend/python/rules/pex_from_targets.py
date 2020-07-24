# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import logging
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from pkg_resources import Requirement, parse_requirements

from pants.backend.python.rules.pex import (
    PexInterpreterConstraints,
    PexPlatforms,
    PexRequest,
    PexRequirements,
    TwoStepPexRequest,
)
from pants.backend.python.rules.python_sources import (
    StrippedPythonSources,
    StrippedPythonSourcesRequest,
)
from pants.backend.python.target_types import (
    PythonInterpreterCompatibility,
    PythonRequirementsField,
)
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import Digest, DigestContents, MergeDigests, PathGlobs, Snapshot
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.engine.target import TransitiveTargets
from pants.option.custom_types import GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexFromTargetsRequest:
    """Request to create a PEX from the closure of a set of targets."""

    addresses: Addresses
    output_filename: str
    distributed_to_users: bool
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
        addresses: Iterable[Address],
        *,
        output_filename: str,
        distributed_to_users: bool,
        entry_point: Optional[str] = None,
        platforms: PexPlatforms = PexPlatforms(),
        additional_args: Iterable[str] = (),
        additional_requirements: Iterable[str] = (),
        include_source_files: bool = True,
        additional_sources: Optional[Digest] = None,
        additional_inputs: Optional[Digest] = None,
        description: Optional[str] = None,
    ) -> None:
        self.addresses = Addresses(addresses)
        self.output_filename = output_filename
        self.distributed_to_users = distributed_to_users
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


@rule
async def pex_from_targets(request: PexFromTargetsRequest, python_setup: PythonSetup) -> PexRequest:
    transitive_targets = await Get(TransitiveTargets, Addresses, request.addresses)
    all_targets = transitive_targets.closure

    input_digests = []
    if request.additional_sources:
        input_digests.append(request.additional_sources)
    if request.include_source_files:
        prepared_sources = await Get(
            StrippedPythonSources, StrippedPythonSourcesRequest(all_targets)
        )
        input_digests.append(prepared_sources.snapshot.digest)
    merged_input_digest = await Get(Digest, MergeDigests(input_digests))

    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (
            tgt[PythonInterpreterCompatibility]
            for tgt in all_targets
            if tgt.has_field(PythonInterpreterCompatibility)
        ),
        python_setup,
    )

    exact_reqs = PexRequirements.create_from_requirement_fields(
        (
            tgt[PythonRequirementsField]
            for tgt in all_targets
            if tgt.has_field(PythonRequirementsField)
        ),
        additional_requirements=request.additional_requirements,
    )

    requirements = exact_reqs

    if python_setup.requirement_constraints:
        exact_req_projects = {Requirement.parse(req).project_name for req in exact_reqs}
        constraint_file_snapshot = await Get(
            Snapshot,
            PathGlobs(
                [python_setup.requirement_constraints],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                conjunction=GlobExpansionConjunction.all_match,
                description_of_origin="the option `--python-setup-requirement-constraints`",
            ),
        )
        constraints_file_contents = await Get(
            DigestContents, Digest, constraint_file_snapshot.digest
        )
        constraints_file_reqs = set(
            parse_requirements(next(iter(constraints_file_contents)).content.decode())
        )
        constraint_file_projects = {req.project_name for req in constraints_file_reqs}
        unconstrained_projects = exact_req_projects - constraint_file_projects
        if unconstrained_projects:
            logger.warning(
                f"The constraints file {python_setup.requirement_constraints} does not contain "
                f"entries for the following requirements: {', '.join(unconstrained_projects)}"
            )

        if python_setup.options.resolve_all_constraints:
            if unconstrained_projects:
                logger.warning(
                    "Ignoring resolve_all_constraints setting in [python_setup] scope"
                    "Because constraints file does not cover all requirements."
                )
            else:
                requirements = PexRequirements(str(req) for req in constraints_file_reqs)
    elif python_setup.options.resolve_all_constraints:
        raise ValueError(
            "resolve_all_constraints in the [python-setup] scope is set, so "
            "requirement_constraints in [python-setup] must also be provided."
        )

    return PexRequest(
        output_filename=request.output_filename,
        distributed_to_users=request.distributed_to_users,
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
    pex_request = await Get(PexRequest, PexFromTargetsRequest, req.pex_from_targets_request)
    return TwoStepPexRequest(pex_request=pex_request)


def rules():
    return [
        pex_from_targets,
        two_step_pex_from_targets,
        RootRule(PexFromTargetsRequest),
        RootRule(TwoStepPexFromTargetsRequest),
    ]
