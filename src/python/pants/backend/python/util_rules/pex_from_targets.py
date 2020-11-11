# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import itertools
import logging
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from packaging.utils import canonicalize_name as canonicalize_project_name
from pkg_resources import Requirement, parse_requirements

from pants.backend.python.target_types import PythonRequirementsField
from pants.backend.python.util_rules.pex import (
    PexInterpreterConstraints,
    PexPlatforms,
    PexRequest,
    PexRequirements,
    TwoStepPexRequest,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.backend.python.util_rules.python_sources import rules as python_sources_rules
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import (
    Digest,
    DigestContents,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.python.python_setup import PythonSetup, ResolveAllConstraintsOption
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexFromTargetsRequest:
    addresses: Addresses
    output_filename: str
    internal_only: bool
    entry_point: Optional[str]
    platforms: PexPlatforms
    additional_args: Tuple[str, ...]
    additional_requirements: Tuple[str, ...]
    include_source_files: bool
    additional_sources: Optional[Digest]
    additional_inputs: Optional[Digest]
    hardcoded_interpreter_constraints: Optional[PexInterpreterConstraints]
    direct_deps_only: bool
    # This field doesn't participate in comparison (and therefore hashing), as it doesn't affect
    # the result.
    description: Optional[str] = dataclasses.field(compare=False)

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        output_filename: str,
        internal_only: bool,
        entry_point: Optional[str] = None,
        platforms: PexPlatforms = PexPlatforms(),
        additional_args: Iterable[str] = (),
        additional_requirements: Iterable[str] = (),
        include_source_files: bool = True,
        additional_sources: Optional[Digest] = None,
        additional_inputs: Optional[Digest] = None,
        hardcoded_interpreter_constraints: Optional[PexInterpreterConstraints] = None,
        direct_deps_only: bool = False,
        description: Optional[str] = None,
    ) -> None:
        """Request to create a Pex from the transitive closure of the given addresses.

        :param addresses: The addresses to use for determining what is included in the Pex. The
            transitive closure of these addresses will be used; you only need to specify the roots.
        :param output_filename: The name of the built Pex file, which typically should end in
            `.pex`.
        :param internal_only: Whether we ever materialize the Pex and distribute it directly
            to end users, such as with the `binary` goal. Typically, instead, the user never
            directly uses the Pex, e.g. with `lint` and `test`. If True, we will use a Pex setting
            that results in faster build time but compatibility with fewer interpreters at runtime.
        :param entry_point: The entry-point for the built Pex, equivalent to Pex's `-m` flag. If
            left off, the Pex will open up as a REPL.
        :param platforms: Which platforms should be supported. Setting this value will cause
            interpreter constraints to not be used because platforms already constrain the valid
            Python versions, e.g. by including `cp36m` in the platform string.
        :param additional_args: Any additional Pex flags.
        :param additional_requirements: Additional requirements to install, in addition to any
            requirements used by the transitive closure of the given addresses.
        :param include_source_files: Whether to include source files in the built Pex or not.
            Setting this to `False` and loading the source files by instead populating the chroot
            and setting the environment variable `PEX_EXTRA_SYS_PATH` will result in substantially
            fewer rebuilds of the Pex.
        :param additional_sources: Any additional source files to include in the built Pex.
        :param additional_inputs: Any inputs that are not source files and should not be included
            directly in the Pex, but should be present in the environment when building the Pex.
        :param hardcoded_interpreter_constraints: Use these constraints rather than resolving the
            constraints from the input.
        :param direct_deps_only: Only consider the input addresses and their direct dependencies,
            rather than the transitive closure.
        :param description: A human-readable description to render in the dynamic UI when building
            the Pex.
        """
        self.addresses = Addresses(addresses)
        self.output_filename = output_filename
        self.internal_only = internal_only
        self.entry_point = entry_point
        self.platforms = platforms
        self.additional_args = tuple(additional_args)
        self.additional_requirements = tuple(additional_requirements)
        self.include_source_files = include_source_files
        self.additional_sources = additional_sources
        self.additional_inputs = additional_inputs
        self.hardcoded_interpreter_constraints = hardcoded_interpreter_constraints
        self.direct_deps_only = direct_deps_only
        self.description = description

    @classmethod
    def for_requirements(
        cls,
        addresses: Iterable[Address],
        *,
        internal_only: bool,
        hardcoded_interpreter_constraints: Optional[PexInterpreterConstraints] = None,
        zip_safe: bool = False,
        direct_deps_only: bool = False,
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
            hardcoded_interpreter_constraints=hardcoded_interpreter_constraints,
            internal_only=internal_only,
            direct_deps_only=direct_deps_only,
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


@rule(level=LogLevel.DEBUG)
async def pex_from_targets(request: PexFromTargetsRequest, python_setup: PythonSetup) -> PexRequest:
    if request.direct_deps_only:
        targets = await Get(Targets, Addresses(request.addresses))
        direct_deps = await MultiGet(
            Get(Targets, DependenciesRequest(tgt.get(Dependencies))) for tgt in targets
        )
        all_targets = FrozenOrderedSet(itertools.chain(*direct_deps, targets))
    else:
        transitive_targets = await Get(
            TransitiveTargets, TransitiveTargetsRequest(request.addresses)
        )
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

    if request.hardcoded_interpreter_constraints:
        interpreter_constraints = request.hardcoded_interpreter_constraints
    else:
        calculated_constraints = PexInterpreterConstraints.create_from_targets(
            all_targets, python_setup
        )
        # If there are no targets, we fall back to the global constraints. This is relevant,
        # for example, when running `./pants repl` with no specs.
        interpreter_constraints = calculated_constraints or PexInterpreterConstraints(
            python_setup.interpreter_constraints
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
        # In requirement strings Foo_-Bar.BAZ and foo-bar-baz refer to the same project. We let
        # packaging canonicalize for us.
        # See: https://www.python.org/dev/peps/pep-0503/#normalized-names

        exact_req_projects = {
            canonicalize_project_name(Requirement.parse(req).project_name) for req in exact_reqs
        }
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
        constraint_file_projects = {
            canonicalize_project_name(req.project_name) for req in constraints_file_reqs
        }
        unconstrained_projects = exact_req_projects - constraint_file_projects
        if unconstrained_projects:
            logger.warning(
                f"The constraints file {python_setup.requirement_constraints} does not contain "
                f"entries for the following requirements: {', '.join(unconstrained_projects)}"
            )

        if python_setup.resolve_all_constraints == ResolveAllConstraintsOption.ALWAYS or (
            python_setup.resolve_all_constraints == ResolveAllConstraintsOption.NONDEPLOYABLES
            and request.internal_only
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
        internal_only=request.internal_only,
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
    return (*collect_rules(), *pex_rules(), *python_sources_rules())
