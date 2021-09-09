# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import logging
from dataclasses import dataclass
from typing import Iterable, Tuple

from packaging.utils import canonicalize_name as canonicalize_project_name
from pkg_resources import Requirement

from pants.backend.python.target_types import (
    MainSpecification,
    PythonRequirementsField,
    parse_requirements_file,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import (
    Lockfile,
    PexPlatforms,
    PexRequest,
    PexRequirements,
    ResolvedDistributions,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.backend.python.util_rules.python_sources import rules as python_sources_rules
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import Digest, DigestContents, GlobMatchErrorBehavior, MergeDigests, PathGlobs
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.python.python_setup import PythonSetup
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
    main: MainSpecification | None
    platforms: PexPlatforms
    additional_args: Tuple[str, ...]
    additional_lockfile_args: Tuple[str, ...]
    additional_requirements: Tuple[str, ...]
    include_source_files: bool
    additional_sources: Digest | None
    additional_inputs: Digest | None
    hardcoded_interpreter_constraints: InterpreterConstraints | None
    direct_deps_only: bool
    # This field doesn't participate in comparison (and therefore hashing), as it doesn't affect
    # the result.
    description: str | None = dataclasses.field(compare=False)

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        output_filename: str,
        internal_only: bool,
        main: MainSpecification | None = None,
        platforms: PexPlatforms = PexPlatforms(),
        additional_args: Iterable[str] = (),
        additional_lockfile_args: Iterable[str] = (),
        additional_requirements: Iterable[str] = (),
        include_source_files: bool = True,
        additional_sources: Digest | None = None,
        additional_inputs: Digest | None = None,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        direct_deps_only: bool = False,
        description: str | None = None,
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
        :param main: The main for the built Pex, equivalent to Pex's `-e` or `-c` flag. If
            left off, the Pex will open up as a REPL.
        :param platforms: Which platforms should be supported. Setting this value will cause
            interpreter constraints to not be used because platforms already constrain the valid
            Python versions, e.g. by including `cp36m` in the platform string.
        :param additional_args: Any additional Pex flags.
        :param additional_lockfile_args: Any additional Pex flags that should be used with the lockfile.pex.
            Many Pex args like `--emit-warnings` do not impact the lockfile, and setting them
            would reduce reuse with other call sites. Generally, this should only be flags that
            impact lockfile resolution like `--manylinux`.
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
        self.main = main
        self.platforms = platforms
        self.additional_args = tuple(additional_args)
        self.additional_lockfile_args = tuple(additional_lockfile_args)
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
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        zip_safe: bool = False,
        direct_deps_only: bool = False,
    ) -> PexFromTargetsRequest:
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
class _ConstraintsResolvedDistributions:
    maybe_resolved_dists: ResolvedDistributions | None


@dataclass(frozen=True)
class _ConstraintsResolvedDistributionsRequest:
    requirements: PexRequirements
    platforms: PexPlatforms
    interpreter_constraints: InterpreterConstraints
    internal_only: bool
    additional_lockfile_args: tuple[str, ...]


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
        calculated_constraints = InterpreterConstraints.create_from_targets(
            all_targets, python_setup
        )
        # If there are no targets, we fall back to the global constraints. This is relevant,
        # for example, when running `./pants repl` with no specs.
        interpreter_constraints = calculated_constraints or InterpreterConstraints(
            python_setup.interpreter_constraints
        )

    requirements = PexRequirements.create_from_requirement_fields(
        (
            tgt[PythonRequirementsField]
            for tgt in all_targets
            if tgt.has_field(PythonRequirementsField)
        ),
        additional_requirements=request.additional_requirements,
    )

    description = request.description

    if requirements:
        resolved_dists: ResolvedDistributions | None = None
        if python_setup.requirement_constraints:
            constraints_resolved_dists = await Get(
                _ConstraintsResolvedDistributions,
                _ConstraintsResolvedDistributionsRequest(
                    requirements,
                    request.platforms,
                    interpreter_constraints,
                    request.internal_only,
                    request.additional_lockfile_args,
                ),
            )
            resolved_dists = constraints_resolved_dists.maybe_resolved_dists
        elif (
            python_setup.resolve_all_constraints
            and python_setup.resolve_all_constraints_was_set_explicitly()
        ):
            raise ValueError(
                "`[python-setup].resolve_all_constraints` is enabled, so "
                "`[python-setup].requirement_constraints` must also be set."
            )
        elif python_setup.lockfile:
            resolved_dists = await Get(
                ResolvedDistributions,
                PexRequest(
                    description=f"Resolving {python_setup.lockfile}",
                    output_filename="lockfile.pex",
                    internal_only=request.internal_only,
                    requirements=Lockfile(
                        file_path=python_setup.lockfile,
                        file_path_description_of_origin=(
                            "the option `[python-setup].experimental_lockfile`"
                        ),
                        # TODO(#12314): Hook up lockfile staleness check once multiple lockfiles
                        # are supported.
                        lockfile_hex_digest=None,
                    ),
                    interpreter_constraints=interpreter_constraints,
                    platforms=request.platforms,
                    additional_args=request.additional_lockfile_args,
                ),
            )
        requirements = dataclasses.replace(requirements, resolved_dists=resolved_dists)

    return PexRequest(
        output_filename=request.output_filename,
        internal_only=request.internal_only,
        requirements=requirements,
        interpreter_constraints=interpreter_constraints,
        platforms=request.platforms,
        main=request.main,
        sources=merged_input_digest,
        additional_inputs=request.additional_inputs,
        additional_args=request.additional_args,
        description=description,
    )


@rule
async def _setup_constraints_repository_pex(
    request: _ConstraintsResolvedDistributionsRequest, python_setup: PythonSetup
) -> _ConstraintsResolvedDistributions:
    # NB: it isn't safe to resolve against the whole constraints file if
    # platforms are in use. See https://github.com/pantsbuild/pants/issues/12222.
    if not python_setup.resolve_all_constraints or request.platforms:
        return _ConstraintsResolvedDistributions(None)

    constraints_path = python_setup.requirement_constraints
    assert constraints_path is not None

    constraints_file_contents = await Get(
        DigestContents,
        PathGlobs(
            [constraints_path],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `[python-setup].requirement_constraints`",
        ),
    )
    constraints_file_reqs = set(
        parse_requirements_file(
            constraints_file_contents[0].content.decode(), rel_path=constraints_path
        )
    )

    # In requirement strings, Foo_-Bar.BAZ and foo-bar-baz refer to the same project. We let
    # packaging canonicalize for us.
    # See: https://www.python.org/dev/peps/pep-0503/#normalized-names
    url_reqs = set()  # E.g., 'foobar@ git+https://github.com/foo/bar.git@branch'
    name_reqs = set()  # E.g., foobar>=1.2.3
    name_req_projects = set()

    for req_str in request.requirements.req_strings:
        req = Requirement.parse(req_str)
        if req.url:  # type: ignore[attr-defined]
            url_reqs.add(req)
        else:
            name_reqs.add(req)
            name_req_projects.add(canonicalize_project_name(req.project_name))

    constraint_file_projects = {
        canonicalize_project_name(req.project_name) for req in constraints_file_reqs
    }
    # Constraints files must only contain name reqs, not URL reqs (those are already
    # constrained by their very nature). See https://github.com/pypa/pip/issues/8210.
    unconstrained_projects = name_req_projects - constraint_file_projects
    if unconstrained_projects:
        logger.warning(
            f"The constraints file {constraints_path} does not contain "
            f"entries for the following requirements: {', '.join(unconstrained_projects)}.\n\n"
            f"Ignoring `[python_setup].resolve_all_constraints` option."
        )
        return _ConstraintsResolvedDistributions(None)

    # To get a full set of requirements we must add the URL requirements to the
    # constraints file, since the latter cannot contain URL requirements.
    # NB: We can only add the URL requirements we know about here, i.e., those that
    #  are transitive deps of the targets in play. There may be others in the repo.
    #  So we may end up creating a few different repository pexes, each with identical
    #  name requirements but different subsets of URL requirements. Fortunately since
    #  all these repository pexes will have identical pinned versions of everything,
    #  this is not a correctness issue, only a performance one.
    all_constraints = {str(req) for req in (constraints_file_reqs | url_reqs)}
    resolved_dists = await Get(
        ResolvedDistributions,
        PexRequest(
            description=f"Resolving {constraints_path}",
            output_filename="repository.pex",
            internal_only=request.internal_only,
            requirements=PexRequirements(all_constraints, apply_constraints=True),
            interpreter_constraints=request.interpreter_constraints,
            platforms=request.platforms,
            additional_args=request.additional_lockfile_args,
        ),
    )
    return _ConstraintsResolvedDistributions(resolved_dists)


def rules():
    return (*collect_rules(), *pex_rules(), *python_sources_rules())
