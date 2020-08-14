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
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.backend.python.target_types import (
    PythonInterpreterCompatibility,
    PythonRequirementsField,
)
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import (
    Digest,
    DigestContents,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.rules import Get, RootRule, collect_rules, rule
from pants.engine.target import TransitiveTargets
from pants.python.python_setup import PythonSetup, ResolveAllConstraintsOption
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


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
    # Is this request for building a deployable binary?
    for_deployable_binary: bool

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        output_filename: str,
        entry_point: Optional[str] = None,
        platforms: PexPlatforms = PexPlatforms(),
        additional_args: Iterable[str] = (),
        additional_requirements: Iterable[str] = (),
        include_source_files: bool = True,
        additional_sources: Optional[Digest] = None,
        additional_inputs: Optional[Digest] = None,
        description: Optional[str] = None,
        for_deployable_binary: bool = False,
    ) -> None:
        self.addresses = Addresses(addresses)
        self.output_filename = output_filename
        self.entry_point = entry_point
        self.platforms = platforms
        self.additional_args = tuple(additional_args)
        self.additional_requirements = tuple(additional_requirements)
        self.include_source_files = include_source_files
        self.additional_sources = additional_sources
        self.additional_inputs = additional_inputs
        self.description = description
        self.for_deployable_binary = for_deployable_binary

    @classmethod
    def for_requirements(
        cls, addresses: Addresses, *, zip_safe: bool = False
    ) -> "PexFromTargetsRequest":
        """Create an instance that can be used to get a requirements pex.

        Useful to ensure that these requests are uniform (e.g., the using the same output filename),
        so that the underlying pexes are more likely to be reused instead of re-resolved.

        We default to zip_safe=False because there are various issues with running zipped pexes
        directly, and it's best to only use those if you're sure it's the right thing to do.
        Also, pytest must use zip_safe=False for performance reasons (see comment in
        pytest_runner.py) and we get more re-use of pexes if other uses follow suit.
        This default is a helpful nudge in that direction.
        """
        return PexFromTargetsRequest(
            addresses=sorted(addresses),
            output_filename="requirements.pex",
            include_source_files=False,
            additional_args=() if zip_safe else ("--not-zip-safe",),
        )


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
            StrippedPythonSourceFiles, PythonSourceFilesRequest(all_targets)
        )
        input_digests.append(prepared_sources.stripped_source_files.snapshot.digest)
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
    description = request.description

    if python_setup.requirement_constraints:
        # In requirement strings Foo_Bar and foo-bar refer to the same project.
        def canonical(name: str) -> str:
            return name.lower().replace("_", "-")

        exact_req_projects = {canonical(Requirement.parse(req).project_name) for req in exact_reqs}
        constraints_file_contents = await Get(
            DigestContents,
            PathGlobs(
                [python_setup.requirement_constraints],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                conjunction=GlobExpansionConjunction.all_match,
                description_of_origin="the option `--python-setup-requirement-constraints`",
            ),
        )
        constraints_file_reqs = set(
            parse_requirements(next(iter(constraints_file_contents)).content.decode())
        )
        constraint_file_projects = {canonical(req.project_name) for req in constraints_file_reqs}
        unconstrained_projects = exact_req_projects - constraint_file_projects
        if unconstrained_projects:
            logger.warning(
                f"The constraints file {python_setup.requirement_constraints} does not contain "
                f"entries for the following requirements: {', '.join(unconstrained_projects)}"
            )

        if python_setup.resolve_all_constraints == ResolveAllConstraintsOption.ALWAYS or (
            python_setup.resolve_all_constraints == ResolveAllConstraintsOption.NONDEPLOYABLES
            and not request.for_deployable_binary
        ):
            if unconstrained_projects:
                logger.warning(
                    "Ignoring resolve_all_constraints setting in [python_setup] scope "
                    "because constraints file does not cover all requirements."
                )
            else:
                requirements = PexRequirements(str(req) for req in constraints_file_reqs)
                description = description or f"Resolving {python_setup.requirement_constraints}"
    elif (
        python_setup.resolve_all_constraints != ResolveAllConstraintsOption.NEVER
        and python_setup.resolve_all_constraints_was_set_explicitly()
    ):
        raise ValueError(
            f"[python-setup].resolve_all_constraints is set to "
            f"{python_setup.resolve_all_constraints.value}, so "
            f"[python-setup].requirement_constraints must also be provided."
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
        description=description,
    )


@rule
async def two_step_pex_from_targets(req: TwoStepPexFromTargetsRequest) -> TwoStepPexRequest:
    pex_request = await Get(PexRequest, PexFromTargetsRequest, req.pex_from_targets_request)
    return TwoStepPexRequest(pex_request=pex_request)


def rules():
    return [
        *collect_rules(),
        RootRule(PexFromTargetsRequest),
        RootRule(TwoStepPexFromTargetsRequest),
    ]
