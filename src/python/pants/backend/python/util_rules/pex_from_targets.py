# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    MainSpecification,
    PexLayout,
    PythonRequirementCompatibleResolvesField,
    PythonRequirementsField,
    PythonResolveField,
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
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import Digest, DigestContents, GlobMatchErrorBehavior, MergeDigests, PathGlobs
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target, TransitiveTargets, TransitiveTargetsRequest
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import bullet_list, path_safe

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
    hardcoded_interpreter_constraints: InterpreterConstraints | None
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
        self.description = description

    def to_interpreter_constraints_request(self) -> InterpreterConstraintsRequest:
        return InterpreterConstraintsRequest(
            addresses=self.addresses,
            hardcoded_interpreter_constraints=self.hardcoded_interpreter_constraints,
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class InterpreterConstraintsRequest:
    addresses: Addresses
    hardcoded_interpreter_constraints: InterpreterConstraints | None

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
    ) -> None:
        self.addresses = Addresses(addresses)
        self.hardcoded_interpreter_constraints = hardcoded_interpreter_constraints


@rule
async def interpreter_constraints_for_targets(
    request: InterpreterConstraintsRequest, python_setup: PythonSetup
) -> InterpreterConstraints:
    if request.hardcoded_interpreter_constraints:
        return request.hardcoded_interpreter_constraints

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))
    calculated_constraints = InterpreterConstraints.create_from_targets(
        transitive_targets.closure, python_setup
    )
    # If there are no targets, we fall back to the global constraints. This is relevant,
    # for example, when running `./pants repl` with no specs.
    interpreter_constraints = calculated_constraints or InterpreterConstraints(
        python_setup.interpreter_constraints
    )
    return interpreter_constraints


@dataclass(frozen=True)
class ChosenPythonResolve:
    name: str
    lockfile_path: str


@dataclass(frozen=True)
class ChosenPythonResolveRequest:
    addresses: Addresses


# Note: Inspired by `coursier_fetch.py`.
class NoCompatibleResolveException(Exception):
    """No compatible resolve could be found for a set of targets."""

    def __init__(
        self, python_setup: PythonSetup, msg_prefix: str, relevant_targets: Iterable[Target]
    ) -> None:
        resolves_to_addresses = defaultdict(list)
        for tgt in relevant_targets:
            if tgt.has_field(PythonResolveField):
                resolve = tgt[PythonResolveField].normalized_value(python_setup)
                resolves_to_addresses[resolve].append(tgt.address.spec)
            elif tgt.has_field(PythonRequirementCompatibleResolvesField):
                resolves = tgt[PythonRequirementCompatibleResolvesField].normalized_value(
                    python_setup
                )
                for resolve in resolves:
                    resolves_to_addresses[resolve].append(tgt.address.spec)

        formatted_resolve_lists = "\n\n".join(
            f"{resolve}:\n{bullet_list(sorted(addresses))}"
            for resolve, addresses in sorted(resolves_to_addresses.items())
        )
        super().__init__(
            f"{msg_prefix}:\n\n"
            f"{formatted_resolve_lists}\n\n"
            "Targets which will be used together must all have the same resolve (from the "
            f"[resolve]({doc_url('reference-python_test#codeexperimental_resolvecode')}) or "
            f"[compatible_resolves]({doc_url('reference-python_requirement#codeexperimental_compatible_resolvescode')}) "
            "fields) in common."
        )


@rule
async def choose_python_resolve(
    request: ChosenPythonResolveRequest, python_setup: PythonSetup
) -> ChosenPythonResolve:
    # If there are no targets, we fall back to the default resolve. This is relevant,
    # for example, when running `./pants repl` with no specs.
    if not request.addresses:
        return ChosenPythonResolve(
            name=python_setup.default_resolve,
            lockfile_path=python_setup.resolves[python_setup.default_resolve],
        )

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))

    # First, choose the resolve by inspecting the root targets.
    root_resolves = {
        root[PythonResolveField].normalized_value(python_setup)
        for root in transitive_targets.roots
        if root.has_field(PythonResolveField)
    }
    if not root_resolves:
        root_targets = bullet_list(
            f"{tgt.address.spec} ({tgt.alias})" for tgt in transitive_targets.roots
        )
        raise AssertionError(
            "Used `ChosenPythonResolveRequest` with input addresses that don't have the "
            f"`PythonResolveField` field registered:\n\n{root_targets}\n\n"
            "If you encountered this bug while using core Pants functionality, please open a "
            "bug at https://github.com/pantsbuild/pants/issues/new with this error message when "
            "`--print-stacktrace` is enabled. If this is from your own plugin, register "
            "`PythonResolveField` on the relevant target types."
        )
    if len(root_resolves) > 1:
        raise NoCompatibleResolveException(
            python_setup,
            "The input targets did not have a resolve in common",
            transitive_targets.roots,
        )

    chosen_resolve = next(iter(root_resolves))

    # Then, validate that all transitive deps are compatible.
    for tgt in transitive_targets.dependencies:
        invalid_resolve_field = (
            tgt.has_field(PythonResolveField)
            and tgt[PythonResolveField].normalized_value(python_setup) != chosen_resolve
        )
        invalid_compatible_resolves_field = tgt.has_field(
            PythonRequirementCompatibleResolvesField
        ) and not any(
            resolve == chosen_resolve
            for resolve in tgt[PythonRequirementCompatibleResolvesField].normalized_value(
                python_setup
            )
        )
        if invalid_resolve_field or invalid_compatible_resolves_field:
            plural = ("s", "their") if len(transitive_targets.roots) > 1 else ("", "its")
            raise NoCompatibleResolveException(
                python_setup,
                (
                    f"The resolve chosen for the root target{plural[0]} was {chosen_resolve}, but "
                    f"some of {plural[1]} dependencies are not compatible with that resolve"
                ),
                transitive_targets.closure,
            )

    return ChosenPythonResolve(
        name=chosen_resolve, lockfile_path=python_setup.resolves[chosen_resolve]
    )


class GlobalRequirementConstraints(DeduplicatedCollection[PipRequirement]):
    """Global constraints specified by the `[python].requirement_constraints` setting, if any."""


@rule
async def global_requirement_constraints(
    python_setup: PythonSetup,
) -> GlobalRequirementConstraints:
    if not python_setup.requirement_constraints:
        return GlobalRequirementConstraints()

    constraints_file_contents = await Get(
        DigestContents,
        PathGlobs(
            [python_setup.requirement_constraints],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `[python].requirement_constraints`",
        ),
    )

    return GlobalRequirementConstraints(
        parse_requirements_file(
            constraints_file_contents[0].content.decode(),
            rel_path=constraints_file_contents[0].path,
        )
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class _RepositoryPexRequest:
    addresses: Addresses
    hardcoded_interpreter_constraints: InterpreterConstraints | None
    platforms: PexPlatforms
    internal_only: bool
    additional_lockfile_args: tuple[str, ...]
    additional_requirements: tuple[str, ...]

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        internal_only: bool,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        platforms: PexPlatforms = PexPlatforms(),
        additional_lockfile_args: tuple[str, ...] = (),
        additional_requirements: tuple[str, ...] = (),
    ) -> None:
        self.addresses = Addresses(addresses)
        self.internal_only = internal_only
        self.hardcoded_interpreter_constraints = hardcoded_interpreter_constraints
        self.platforms = platforms
        self.additional_lockfile_args = additional_lockfile_args
        self.additional_requirements = additional_requirements

    def to_interpreter_constraints_request(self) -> InterpreterConstraintsRequest:
        return InterpreterConstraintsRequest(
            addresses=self.addresses,
            hardcoded_interpreter_constraints=self.hardcoded_interpreter_constraints,
        )


@dataclass(frozen=True)
class _ConstraintsRepositoryPexRequest:
    repository_pex_request: _RepositoryPexRequest


@rule(level=LogLevel.DEBUG)
async def pex_from_targets(
    request: PexFromTargetsRequest,
    global_requirement_constraints: GlobalRequirementConstraints,
) -> PexRequest:
    interpreter_constraints = await Get(
        InterpreterConstraints,
        InterpreterConstraintsRequest,
        request.to_interpreter_constraints_request(),
    )

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))

    sources_digests = []
    if request.additional_sources:
        sources_digests.append(request.additional_sources)
    if request.include_source_files:
        sources = await Get(PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure))
    else:
        sources = PythonSourceFiles.empty()

    additional_inputs_digests = []
    if request.additional_inputs:
        additional_inputs_digests.append(request.additional_inputs)
    additional_args = request.additional_args
    if request.include_local_dists:
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
                for tgt in transitive_targets.closure
                if tgt.has_field(PythonRequirementsField)
            ),
            additional_requirements=request.additional_requirements,
            constraints_strings=(str(constraint) for constraint in global_requirement_constraints),
        )
    else:
        requirements = PexRequirements()

    if requirements:
        repository_pex = await Get(
            OptionalPex,
            _RepositoryPexRequest(
                request.addresses,
                hardcoded_interpreter_constraints=request.hardcoded_interpreter_constraints,
                platforms=request.platforms,
                internal_only=request.internal_only,
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
    elif python_setup.enable_resolves:
        chosen_resolve = await Get(
            ChosenPythonResolve, ChosenPythonResolveRequest(request.addresses)
        )
        repository_pex_request = PexRequest(
            description=(
                f"Installing {chosen_resolve.lockfile_path} for the resolve `{chosen_resolve.name}`"
            ),
            output_filename=f"{path_safe(chosen_resolve.name)}_lockfile.pex",
            internal_only=request.internal_only,
            requirements=Lockfile(
                file_path=chosen_resolve.lockfile_path,
                file_path_description_of_origin=(
                    f"the resolve `{chosen_resolve.name}` (from `[python].experimental_resolves`)"
                ),
                # TODO(#12314): Hook up lockfile staleness check.
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
    constraints_request: _ConstraintsRepositoryPexRequest,
    python_setup: PythonSetup,
    global_requirement_constraints: GlobalRequirementConstraints,
) -> OptionalPexRequest:
    request = constraints_request.repository_pex_request
    # NB: it isn't safe to resolve against the whole constraints file if
    # platforms are in use. See https://github.com/pantsbuild/pants/issues/12222.
    if not python_setup.resolve_all_constraints or request.platforms:
        return OptionalPexRequest(None)

    constraints_path = python_setup.requirement_constraints
    assert constraints_path is not None

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))

    requirements = PexRequirements.create_from_requirement_fields(
        (
            tgt[PythonRequirementsField]
            for tgt in transitive_targets.closure
            if tgt.has_field(PythonRequirementsField)
        ),
        additional_requirements=request.additional_requirements,
        constraints_strings=(str(constraint) for constraint in global_requirement_constraints),
    )

    # In requirement strings, Foo_-Bar.BAZ and foo-bar-baz refer to the same project. We let
    # packaging canonicalize for us.
    # See: https://www.python.org/dev/peps/pep-0503/#normalized-names
    url_reqs = set()  # E.g., 'foobar@ git+https://github.com/foo/bar.git@branch'
    name_reqs = set()  # E.g., foobar>=1.2.3
    name_req_projects = set()
    constraints_file_reqs = set(global_requirement_constraints)

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
            constraints_strings=(str(constraint) for constraint in global_requirement_constraints),
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

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        internal_only: bool,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
    ) -> None:
        self.addresses = Addresses(addresses)
        self.internal_only = internal_only
        self.hardcoded_interpreter_constraints = hardcoded_interpreter_constraints


@rule
async def get_requirements_pex(request: RequirementsPexRequest, setup: PythonSetup) -> PexRequest:
    if setup.run_against_entire_lockfile and request.internal_only:
        opt_pex_request = await Get(
            OptionalPexRequest,
            _RepositoryPexRequest(
                addresses=sorted(request.addresses),
                internal_only=request.internal_only,
                hardcoded_interpreter_constraints=request.hardcoded_interpreter_constraints,
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
        ),
    )
    return pex_request


def rules():
    return (*collect_rules(), *pex_rules(), *local_dists_rules(), *python_sources_rules())
