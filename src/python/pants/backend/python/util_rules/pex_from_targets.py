# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import logging
from dataclasses import dataclass
from typing import Iterable

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    MainSpecification,
    PexLayout,
    PythonRequirementsField,
    parse_requirements_file,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists import LocalDistsPex, LocalDistsPexRequest
from pants.backend.python.util_rules.local_dists import rules as local_dists_rules
from pants.backend.python.util_rules.pex import (
    Lockfile,
    OptionalPex,
    OptionalPexRequest,
    PexPlatforms,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
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
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import path_safe

logger = logging.getLogger(__name__)


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexFromTargetsRequest:
    addresses: Addresses
    output_filename: str
    internal_only: bool
    layout: PexLayout | None
    main: MainSpecification | None
    platforms: PexPlatforms
    additional_args: tuple[str, ...]
    additional_lockfile_args: tuple[str, ...]
    additional_requirements: tuple[str, ...]
    include_source_files: bool
    include_requirements: bool
    include_local_dists: bool
    additional_sources: Digest | None
    additional_inputs: Digest | None
    resolve_and_lockfile: tuple[str, str] | None
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
        layout: PexLayout | None = None,
        main: MainSpecification | None = None,
        platforms: PexPlatforms = PexPlatforms(),
        additional_args: Iterable[str] = (),
        additional_lockfile_args: Iterable[str] = (),
        additional_requirements: Iterable[str] = (),
        include_source_files: bool = True,
        include_requirements: bool = True,
        include_local_dists: bool = False,
        additional_sources: Digest | None = None,
        additional_inputs: Digest | None = None,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        resolve_and_lockfile: tuple[str, str] | None = None,
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
        :param layout: The filesystem layout to create the PEX with.
        :param main: The main for the built Pex, equivalent to Pex's `-e` or `-c` flag. If
            left off, the Pex will open up as a REPL.
        :param platforms: Which platforms should be supported. Setting this value will cause
            interpreter constraints to not be used because platforms already constrain the valid
            Python versions, e.g. by including `cp36m` in the platform string.
        :param additional_args: Any additional Pex flags.
        :param additional_lockfile_args: Any additional Pex flags that should be used with the
            lockfile.pex. Many Pex args like `--emit-warnings` do not impact the lockfile, and
            setting them would reduce reuse with other call sites. Generally, these should only be
            flags that impact lockfile resolution like `--manylinux`.
        :param additional_requirements: Additional requirements to install, in addition to any
            requirements used by the transitive closure of the given addresses.
        :param include_source_files: Whether to include source files in the built Pex or not.
            Setting this to `False` and loading the source files by instead populating the chroot
            and setting the environment variable `PEX_EXTRA_SYS_PATH` will result in substantially
            fewer rebuilds of the Pex.
        :param include_requirements: Whether to resolve requirements and include them in the Pex.
        :param include_local_dists: Whether to build local dists and include them in the built pex.
        :param additional_sources: Any additional source files to include in the built Pex.
        :param additional_inputs: Any inputs that are not source files and should not be included
            directly in the Pex, but should be present in the environment when building the Pex.
        :param hardcoded_interpreter_constraints: Use these constraints rather than resolving the
            constraints from the input.
        :param resolve_and_lockfile: if set, use this "named resolve" and lockfile.
        :param direct_deps_only: Only consider the input addresses and their direct dependencies,
            rather than the transitive closure.
        :param description: A human-readable description to render in the dynamic UI when building
            the Pex.
        """
        self.addresses = Addresses(addresses)
        self.output_filename = output_filename
        self.internal_only = internal_only
        self.layout = layout
        self.main = main
        self.platforms = platforms
        self.additional_args = tuple(additional_args)
        self.additional_lockfile_args = tuple(additional_lockfile_args)
        self.additional_requirements = tuple(additional_requirements)
        self.include_source_files = include_source_files
        self.include_requirements = include_requirements
        self.include_local_dists = include_local_dists
        self.additional_sources = additional_sources
        self.additional_inputs = additional_inputs
        self.hardcoded_interpreter_constraints = hardcoded_interpreter_constraints
        self.resolve_and_lockfile = resolve_and_lockfile
        self.direct_deps_only = direct_deps_only
        self.description = description

    def to_interpreter_constraints_request(self) -> InterpreterConstraintsRequest:
        return InterpreterConstraintsRequest(
            addresses=self.addresses,
            hardcoded_interpreter_constraints=self.hardcoded_interpreter_constraints,
            direct_deps_only=self.direct_deps_only,
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class _RelevantTargetsRequest:
    addresses: Addresses
    direct_deps_only: bool

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        direct_deps_only: bool = False,
    ) -> None:
        self.addresses = Addresses(addresses)
        self.direct_deps_only = direct_deps_only


@dataclass(frozen=True)
class _RelevantTargets:
    targets: FrozenOrderedSet[Target]


@rule
async def get_relevant_targets(request: _RelevantTargetsRequest) -> _RelevantTargets:
    if request.direct_deps_only:
        targets = await Get(Targets, Addresses(request.addresses))
        direct_deps = await MultiGet(
            Get(Targets, DependenciesRequest(tgt.get(Dependencies))) for tgt in targets
        )
        relevant_targets = FrozenOrderedSet(itertools.chain(*direct_deps, targets))
    else:
        transitive_targets = await Get(
            TransitiveTargets, TransitiveTargetsRequest(request.addresses)
        )
        relevant_targets = transitive_targets.closure
    return _RelevantTargets(relevant_targets)


@frozen_after_init
@dataclass(unsafe_hash=True)
class InterpreterConstraintsRequest:
    addresses: Addresses
    hardcoded_interpreter_constraints: InterpreterConstraints | None
    direct_deps_only: bool

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        direct_deps_only: bool = False,
    ) -> None:
        self.addresses = Addresses(addresses)
        self.hardcoded_interpreter_constraints = hardcoded_interpreter_constraints
        self.direct_deps_only = direct_deps_only


@rule
async def interpreter_constraints_for_targets(
    request: InterpreterConstraintsRequest, python_setup: PythonSetup
) -> InterpreterConstraints:
    if request.hardcoded_interpreter_constraints:
        return request.hardcoded_interpreter_constraints

    relevant_targets = await Get(
        _RelevantTargets,
        _RelevantTargetsRequest(request.addresses, direct_deps_only=request.direct_deps_only),
    )
    calculated_constraints = InterpreterConstraints.create_from_targets(
        relevant_targets.targets, python_setup
    )
    # If there are no targets, we fall back to the global constraints. This is relevant,
    # for example, when running `./pants repl` with no specs.
    interpreter_constraints = calculated_constraints or InterpreterConstraints(
        python_setup.interpreter_constraints
    )
    return interpreter_constraints


@frozen_after_init
@dataclass(unsafe_hash=True)
class _RepositoryPexRequest:
    addresses: Addresses
    hardcoded_interpreter_constraints: InterpreterConstraints | None
    direct_deps_only: bool
    platforms: PexPlatforms
    internal_only: bool
    resolve_and_lockfile: tuple[str, str] | None
    additional_lockfile_args: tuple[str, ...]
    additional_requirements: tuple[str, ...]

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        internal_only: bool,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        direct_deps_only: bool = False,
        platforms: PexPlatforms = PexPlatforms(),
        resolve_and_lockfile: tuple[str, str] | None = None,
        additional_lockfile_args: tuple[str, ...] = (),
        additional_requirements: tuple[str, ...] = (),
    ) -> None:
        self.addresses = Addresses(addresses)
        self.internal_only = internal_only
        self.hardcoded_interpreter_constraints = hardcoded_interpreter_constraints
        self.direct_deps_only = direct_deps_only
        self.platforms = platforms
        self.resolve_and_lockfile = resolve_and_lockfile
        self.additional_lockfile_args = additional_lockfile_args
        self.additional_requirements = additional_requirements

    def to_interpreter_constraints_request(self) -> InterpreterConstraintsRequest:
        return InterpreterConstraintsRequest(
            addresses=self.addresses,
            hardcoded_interpreter_constraints=self.hardcoded_interpreter_constraints,
            direct_deps_only=self.direct_deps_only,
        )


@dataclass(frozen=True)
class _ConstraintsRepositoryPexRequest:
    repository_pex_request: _RepositoryPexRequest


@rule(level=LogLevel.DEBUG)
async def pex_from_targets(request: PexFromTargetsRequest) -> PexRequest:
    interpreter_constraints = await Get(
        InterpreterConstraints,
        InterpreterConstraintsRequest,
        request.to_interpreter_constraints_request(),
    )

    relevant_targets = await Get(
        _RelevantTargets,
        _RelevantTargetsRequest(request.addresses, direct_deps_only=request.direct_deps_only),
    )

    sources_digests = []
    if request.additional_sources:
        sources_digests.append(request.additional_sources)
    if request.include_source_files:
        sources = await Get(PythonSourceFiles, PythonSourceFilesRequest(relevant_targets.targets))
    else:
        sources = PythonSourceFiles.empty()

    additional_inputs_digests = []
    if request.additional_inputs:
        additional_inputs_digests.append(request.additional_inputs)
    additional_args = request.additional_args
    if request.include_local_dists:
        # Note that LocalDistsPexRequest has no `direct_deps_only` mode, so we will build all
        # local dists in the transitive closure even if the request was for direct_deps_only.
        # Since we currently use `direct_deps_only` in one case (building a requirements pex
        # when running pylint) and in that case include_local_dists=False, this seems harmless.
        local_dists = await Get(
            LocalDistsPex,
            LocalDistsPexRequest(
                request.addresses,
                internal_only=request.internal_only,
                interpreter_constraints=interpreter_constraints,
                sources=sources,
            ),
        )
        remaining_sources = local_dists.remaining_sources
        additional_inputs_digests.append(local_dists.pex.digest)
        additional_args += ("--requirements-pex", local_dists.pex.name)
    else:
        remaining_sources = sources

    remaining_sources_stripped = await Get(
        StrippedPythonSourceFiles, PythonSourceFiles, remaining_sources
    )
    sources_digests.append(remaining_sources_stripped.stripped_source_files.snapshot.digest)

    merged_sources_digest, additional_inputs = await MultiGet(
        Get(Digest, MergeDigests(sources_digests)),
        Get(Digest, MergeDigests(additional_inputs_digests)),
    )

    description = request.description

    if request.include_requirements:
        requirements = PexRequirements.create_from_requirement_fields(
            (
                tgt[PythonRequirementsField]
                for tgt in relevant_targets.targets
                if tgt.has_field(PythonRequirementsField)
            ),
            additional_requirements=request.additional_requirements,
            apply_constraints=True,
        )
    else:
        requirements = PexRequirements()

    if requirements:
        repository_pex = await Get(
            OptionalPex,
            _RepositoryPexRequest(
                request.addresses,
                hardcoded_interpreter_constraints=request.hardcoded_interpreter_constraints,
                direct_deps_only=request.direct_deps_only,
                platforms=request.platforms,
                internal_only=request.internal_only,
                resolve_and_lockfile=request.resolve_and_lockfile,
                additional_lockfile_args=request.additional_lockfile_args,
                additional_requirements=request.additional_requirements,
            ),
        )
        requirements = dataclasses.replace(requirements, repository_pex=repository_pex.maybe_pex)

    return PexRequest(
        output_filename=request.output_filename,
        internal_only=request.internal_only,
        layout=request.layout,
        requirements=requirements,
        interpreter_constraints=interpreter_constraints,
        platforms=request.platforms,
        main=request.main,
        sources=merged_sources_digest,
        additional_inputs=additional_inputs,
        additional_args=additional_args,
        description=description,
    )


@rule
async def get_repository_pex(
    request: _RepositoryPexRequest, python_setup: PythonSetup
) -> OptionalPexRequest:

    interpreter_constraints = await Get(
        InterpreterConstraints,
        InterpreterConstraintsRequest,
        request.to_interpreter_constraints_request(),
    )

    repository_pex_request: PexRequest | None = None
    if python_setup.requirement_constraints:
        constraints_repository_pex_request = await Get(
            OptionalPexRequest,
            _ConstraintsRepositoryPexRequest(request),
        )
        repository_pex_request = constraints_repository_pex_request.maybe_pex_request
    elif (
        python_setup.resolve_all_constraints
        and python_setup.resolve_all_constraints_was_set_explicitly()
    ):
        raise ValueError(
            "`[python].resolve_all_constraints` is enabled, so "
            "`[python].requirement_constraints` must also be set."
        )
    elif request.resolve_and_lockfile:
        resolve, lockfile = request.resolve_and_lockfile
        repository_pex_request = PexRequest(
            description=f"Installing {lockfile} for the resolve `{resolve}`",
            output_filename=f"{path_safe(resolve)}_lockfile.pex",
            internal_only=request.internal_only,
            requirements=Lockfile(
                file_path=lockfile,
                file_path_description_of_origin=(
                    f"the resolve `{resolve}` (from "
                    "`[python].experimental_resolves_to_lockfiles`)"
                ),
                # TODO(#12314): Hook up lockfile staleness check.
                lockfile_hex_digest=None,
                req_strings=None,
            ),
            interpreter_constraints=interpreter_constraints,
            platforms=request.platforms,
            additional_args=request.additional_lockfile_args,
        )
    elif python_setup.lockfile:
        repository_pex_request = PexRequest(
            description=f"Installing {python_setup.lockfile}",
            output_filename="lockfile.pex",
            internal_only=request.internal_only,
            requirements=Lockfile(
                file_path=python_setup.lockfile,
                file_path_description_of_origin="the option `[python].experimental_lockfile`",
                # TODO(#12314): Hook up lockfile staleness check once multiple lockfiles
                # are supported.
                lockfile_hex_digest=None,
                req_strings=None,
            ),
            interpreter_constraints=interpreter_constraints,
            platforms=request.platforms,
            additional_args=request.additional_lockfile_args,
        )
    return OptionalPexRequest(repository_pex_request)


@rule
async def _setup_constraints_repository_pex(
    constraints_request: _ConstraintsRepositoryPexRequest, python_setup: PythonSetup
) -> OptionalPexRequest:
    request = constraints_request.repository_pex_request
    # NB: it isn't safe to resolve against the whole constraints file if
    # platforms are in use. See https://github.com/pantsbuild/pants/issues/12222.
    if not python_setup.resolve_all_constraints or request.platforms:
        return OptionalPexRequest(None)

    constraints_path = python_setup.requirement_constraints
    assert constraints_path is not None

    constraints_file_contents = await Get(
        DigestContents,
        PathGlobs(
            [constraints_path],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `[python].requirement_constraints`",
        ),
    )
    constraints_file_reqs = set(
        parse_requirements_file(
            constraints_file_contents[0].content.decode(), rel_path=constraints_path
        )
    )

    relevant_targets = await Get(
        _RelevantTargets,
        _RelevantTargetsRequest(request.addresses, direct_deps_only=request.direct_deps_only),
    )

    requirements = PexRequirements.create_from_requirement_fields(
        (
            tgt[PythonRequirementsField]
            for tgt in relevant_targets.targets
            if tgt.has_field(PythonRequirementsField)
        ),
        additional_requirements=request.additional_requirements,
        apply_constraints=True,
    )

    # In requirement strings, Foo_-Bar.BAZ and foo-bar-baz refer to the same project. We let
    # packaging canonicalize for us.
    # See: https://www.python.org/dev/peps/pep-0503/#normalized-names
    url_reqs = set()  # E.g., 'foobar@ git+https://github.com/foo/bar.git@branch'
    name_reqs = set()  # E.g., foobar>=1.2.3
    name_req_projects = set()

    for req_str in requirements.req_strings:
        req = PipRequirement.parse(req_str)
        if req.url:
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
        return OptionalPexRequest(None)

    interpreter_constraints = await Get(
        InterpreterConstraints,
        InterpreterConstraintsRequest,
        request.to_interpreter_constraints_request(),
    )

    # To get a full set of requirements we must add the URL requirements to the
    # constraints file, since the latter cannot contain URL requirements.
    # NB: We can only add the URL requirements we know about here, i.e., those that
    #  are transitive deps of the targets in play. There may be others in the repo.
    #  So we may end up creating a few different repository pexes, each with identical
    #  name requirements but different subsets of URL requirements. Fortunately since
    #  all these repository pexes will have identical pinned versions of everything,
    #  this is not a correctness issue, only a performance one.
    all_constraints = {str(req) for req in (constraints_file_reqs | url_reqs)}
    repository_pex = PexRequest(
        description=f"Resolving {constraints_path}",
        output_filename="repository.pex",
        internal_only=request.internal_only,
        requirements=PexRequirements(
            all_constraints,
            apply_constraints=True,
            # TODO: See PexRequirements docs.
            is_all_constraints_resolve=True,
        ),
        interpreter_constraints=interpreter_constraints,
        platforms=request.platforms,
        additional_args=request.additional_lockfile_args,
    )
    return OptionalPexRequest(repository_pex)


@frozen_after_init
@dataclass(unsafe_hash=True)
class RequirementsPexRequest:
    addresses: tuple[Address, ...]
    internal_only: bool
    hardcoded_interpreter_constraints: InterpreterConstraints | None
    direct_deps_only: bool
    resolve_and_lockfile: tuple[str, str] | None

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        internal_only: bool,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        direct_deps_only: bool = False,
        resolve_and_lockfile: tuple[str, str] | None = None,
    ) -> None:
        self.addresses = Addresses(addresses)
        self.internal_only = internal_only
        self.hardcoded_interpreter_constraints = hardcoded_interpreter_constraints
        self.direct_deps_only = direct_deps_only
        self.resolve_and_lockfile = resolve_and_lockfile


@rule
async def get_requirements_pex(request: RequirementsPexRequest, setup: PythonSetup) -> PexRequest:
    if setup.run_against_entire_lockfile and request.internal_only:
        opt_pex_request = await Get(
            OptionalPexRequest,
            _RepositoryPexRequest(
                addresses=sorted(request.addresses),
                internal_only=request.internal_only,
                hardcoded_interpreter_constraints=request.hardcoded_interpreter_constraints,
                direct_deps_only=request.direct_deps_only,
                resolve_and_lockfile=request.resolve_and_lockfile,
            ),
        )
        if opt_pex_request.maybe_pex_request is None:
            raise ValueError(
                "[python].run_against_entire_lockfile was set, but could not find a "
                "lockfile or constraints file for this target set. See "
                f"{doc_url('python-third-party-dependencies')} for details."
            )
        return opt_pex_request.maybe_pex_request

    pex_request = await Get(
        PexRequest,
        PexFromTargetsRequest(
            addresses=sorted(request.addresses),
            output_filename="requirements.pex",
            internal_only=request.internal_only,
            include_source_files=False,
            hardcoded_interpreter_constraints=request.hardcoded_interpreter_constraints,
            direct_deps_only=request.direct_deps_only,
            resolve_and_lockfile=request.resolve_and_lockfile,
        ),
    )
    return pex_request


def rules():
    return (*collect_rules(), *pex_rules(), *local_dists_rules(), *python_sources_rules())
