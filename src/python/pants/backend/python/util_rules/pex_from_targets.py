# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    Executable,
    MainSpecification,
    PexLayout,
    PythonRequirementsField,
    PythonResolveField,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists import LocalDistsPex, LocalDistsPexRequest
from pants.backend.python.util_rules.local_dists import rules as local_dists_rules
from pants.backend.python.util_rules.pex import (
    CompletePlatforms,
    OptionalPex,
    OptionalPexRequest,
    Pex,
    PexPlatforms,
    PexRequest,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_requirements import (
    EntireLockfile,
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    PexRequirements,
    Resolve,
)
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.backend.python.util_rules.python_sources import rules as python_sources_rules
from pants.core.goals.generate_lockfiles import NoCompatibleResolveException
from pants.core.goals.package import TraverseIfNotPackageTarget
from pants.core.target_types import FileSourceField
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import Digest, DigestContents, GlobMatchErrorBehavior, MergeDigests, PathGlobs
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    targets_with_sources_types,
)
from pants.engine.unions import UnionMembership
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.pip_requirement import PipRequirement
from pants.util.requirements import parse_requirements_file
from pants.util.strutil import path_safe, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PexFromTargetsRequest:
    addresses: Addresses
    output_filename: str
    internal_only: bool
    layout: PexLayout | None
    main: MainSpecification | None
    inject_args: tuple[str, ...]
    inject_env: FrozenDict[str, str]
    platforms: PexPlatforms
    complete_platforms: CompletePlatforms
    additional_args: tuple[str, ...]
    additional_lockfile_args: tuple[str, ...]
    include_source_files: bool
    include_requirements: bool
    include_local_dists: bool
    additional_sources: Digest | None
    additional_inputs: Digest | None
    hardcoded_interpreter_constraints: InterpreterConstraints | None
    warn_for_transitive_files_targets: bool
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
        inject_args: Iterable[str] = (),
        inject_env: Mapping[str, str] = FrozenDict(),
        platforms: PexPlatforms = PexPlatforms(),
        complete_platforms: CompletePlatforms = CompletePlatforms(),
        additional_args: Iterable[str] = (),
        additional_lockfile_args: Iterable[str] = (),
        include_source_files: bool = True,
        include_requirements: bool = True,
        include_local_dists: bool = False,
        additional_sources: Digest | None = None,
        additional_inputs: Digest | None = None,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        description: str | None = None,
        warn_for_transitive_files_targets: bool = False,
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
        :param inject_args: Command line arguments to freeze in to the PEX.
        :param inject_env: Environment variables to freeze in to the PEX.
        :param platforms: Which platforms should be supported. Setting this value will cause
            interpreter constraints to not be used because platforms already constrain the valid
            Python versions, e.g. by including `cp36m` in the platform string.
        :param additional_args: Any additional Pex flags.
        :param additional_lockfile_args: Any additional Pex flags that should be used with the
            lockfile.pex. Many Pex args like `--emit-warnings` do not impact the lockfile, and
            setting them would reduce reuse with other call sites. Generally, these should only be
            flags that impact lockfile resolution like `--manylinux`.
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
        :param warn_for_transitive_files_targets: If True (and include_source_files is also true),
            emit a warning if the pex depends on any `files` targets, since they won't be included.
        """
        object.__setattr__(self, "addresses", Addresses(addresses))
        object.__setattr__(self, "output_filename", output_filename)
        object.__setattr__(self, "internal_only", internal_only)
        object.__setattr__(self, "layout", layout)
        object.__setattr__(self, "main", main)
        object.__setattr__(self, "inject_args", tuple(inject_args))
        object.__setattr__(self, "inject_env", FrozenDict(inject_env))
        object.__setattr__(self, "platforms", platforms)
        object.__setattr__(self, "complete_platforms", complete_platforms)
        object.__setattr__(self, "additional_args", tuple(additional_args))
        object.__setattr__(self, "additional_lockfile_args", tuple(additional_lockfile_args))
        object.__setattr__(self, "include_source_files", include_source_files)
        object.__setattr__(self, "include_requirements", include_requirements)
        object.__setattr__(self, "include_local_dists", include_local_dists)
        object.__setattr__(self, "additional_sources", additional_sources)
        object.__setattr__(self, "additional_inputs", additional_inputs)
        object.__setattr__(
            self, "hardcoded_interpreter_constraints", hardcoded_interpreter_constraints
        )
        object.__setattr__(self, "description", description)
        object.__setattr__(
            self, "warn_for_transitive_files_targets", warn_for_transitive_files_targets
        )

        self.__post_init__()

    def __post_init__(self):
        if self.internal_only and (self.platforms or self.complete_platforms):
            raise AssertionError(
                softwrap(
                    """
                    PexFromTargetsRequest set internal_only at the same time as setting
                    `platforms` and/or `complete_platforms`. Platforms can only be used when
                    `internal_only=False`.
                    """
                )
            )

    def to_interpreter_constraints_request(self) -> InterpreterConstraintsRequest:
        return InterpreterConstraintsRequest(
            addresses=self.addresses,
            hardcoded_interpreter_constraints=self.hardcoded_interpreter_constraints,
        )


@dataclass(frozen=True)
class InterpreterConstraintsRequest:
    addresses: Addresses
    hardcoded_interpreter_constraints: InterpreterConstraints | None

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
    ) -> None:
        object.__setattr__(self, "addresses", Addresses(addresses))
        object.__setattr__(
            self, "hardcoded_interpreter_constraints", hardcoded_interpreter_constraints
        )


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
    # for example, when running `./pants repl` with no specs or only on targets without
    # `interpreter_constraints` (e.g. `python_requirement`).
    interpreter_constraints = calculated_constraints or InterpreterConstraints(
        python_setup.interpreter_constraints
    )
    return interpreter_constraints


@dataclass(frozen=True)
class ChosenPythonResolve:
    name: str
    lockfile: Lockfile


@dataclass(frozen=True)
class ChosenPythonResolveRequest:
    addresses: Addresses


@rule
async def choose_python_resolve(
    request: ChosenPythonResolveRequest, python_setup: PythonSetup
) -> ChosenPythonResolve:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))

    def maybe_get_resolve(t: Target) -> str | None:
        if not t.has_field(PythonResolveField):
            return None
        return t[PythonResolveField].normalized_value(python_setup)

    # First, choose the resolve by inspecting the root targets.
    root_resolves = {
        root[PythonResolveField].normalized_value(python_setup)
        for root in transitive_targets.roots
        if root.has_field(PythonResolveField)
    }
    if root_resolves:
        if len(root_resolves) > 1:
            raise NoCompatibleResolveException.bad_input_roots(
                transitive_targets.roots,
                maybe_get_resolve=maybe_get_resolve,
                doc_url_slug="docs/python/overview/lockfiles#multiple-lockfiles",
                workaround=None,
            )

        chosen_resolve = next(iter(root_resolves))

        # Then, validate that all transitive deps are compatible.
        for tgt in transitive_targets.dependencies:
            if (
                tgt.has_field(PythonResolveField)
                and tgt[PythonResolveField].normalized_value(python_setup) != chosen_resolve
            ):
                raise NoCompatibleResolveException.bad_dependencies(
                    maybe_get_resolve=maybe_get_resolve,
                    doc_url_slug="docs/python/overview/lockfiles#multiple-lockfiles",
                    root_resolve=chosen_resolve,
                    root_targets=transitive_targets.roots,
                    dependencies=transitive_targets.dependencies,
                )

    else:
        # If there are no relevant targets, we fall back to the default resolve. This is relevant,
        # for example, when running `./pants repl` with no specs or only on non-Python targets.
        chosen_resolve = python_setup.default_resolve

    return ChosenPythonResolve(
        name=chosen_resolve,
        lockfile=Lockfile(
            url=python_setup.resolves[chosen_resolve],
            url_description_of_origin=(
                f"the resolve `{chosen_resolve}` (from `[python].resolves`)"
            ),
            resolve_name=chosen_resolve,
        ),
    )


class GlobalRequirementConstraints(DeduplicatedCollection[PipRequirement]):
    """Global constraints specified by the `[python].requirement_constraints` setting, if any."""


@rule
async def determine_global_requirement_constraints(
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


@dataclass(frozen=True)
class _PexRequirementsRequest:
    """Determine the requirement strings used transitively.

    This type is private because callers should likely use `RequirementsPexRequest` or
    `PexFromTargetsRequest` instead.
    """

    addresses: Addresses


@rule
async def determine_requirement_strings_in_closure(
    request: _PexRequirementsRequest, global_requirement_constraints: GlobalRequirementConstraints
) -> PexRequirements:
    addrs = request.addresses
    if len(addrs) == 0:
        description_of_origin = ""
    elif len(addrs) == 1:
        description_of_origin = addrs[0].spec
    else:
        description_of_origin = f"{addrs[0].spec} and {len(addrs)-1} other targets"

    return PexRequirements(
        request.addresses,
        # This is only set if `[python].requirement_constraints` is configured, which is mutually
        # exclusive with resolves.
        constraints_strings=(str(constraint) for constraint in global_requirement_constraints),
        description_of_origin=description_of_origin,
    )


@dataclass(frozen=True)
class _RepositoryPexRequest:
    addresses: Addresses
    hardcoded_interpreter_constraints: InterpreterConstraints | None
    platforms: PexPlatforms
    complete_platforms: CompletePlatforms
    internal_only: bool
    additional_lockfile_args: tuple[str, ...]

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        internal_only: bool,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
        platforms: PexPlatforms = PexPlatforms(),
        complete_platforms: CompletePlatforms = CompletePlatforms(),
        additional_lockfile_args: tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "addresses", Addresses(addresses))
        object.__setattr__(self, "internal_only", internal_only)
        object.__setattr__(
            self, "hardcoded_interpreter_constraints", hardcoded_interpreter_constraints
        )
        object.__setattr__(self, "platforms", platforms)
        object.__setattr__(self, "complete_platforms", complete_platforms)
        object.__setattr__(self, "additional_lockfile_args", additional_lockfile_args)

    def to_interpreter_constraints_request(self) -> InterpreterConstraintsRequest:
        return InterpreterConstraintsRequest(
            addresses=self.addresses,
            hardcoded_interpreter_constraints=self.hardcoded_interpreter_constraints,
        )


@dataclass(frozen=True)
class _ConstraintsRepositoryPexRequest:
    repository_pex_request: _RepositoryPexRequest


async def _determine_requirements_for_pex_from_targets(
    request: PexFromTargetsRequest, python_setup: PythonSetup
) -> tuple[PexRequirements | EntireLockfile, Iterable[Pex]]:
    if not request.include_requirements:
        return PexRequirements(), ()

    requirements = await Get(PexRequirements, _PexRequirementsRequest(request.addresses))
    pex_native_subsetting_supported = False
    if python_setup.enable_resolves:
        # TODO: Once `requirement_constraints` is removed in favor of `enable_resolves`,
        # `ChosenPythonResolveRequest` and `_PexRequirementsRequest` should merge and
        # do a single transitive walk to replace this method.
        chosen_resolve = await Get(
            ChosenPythonResolve, ChosenPythonResolveRequest(request.addresses)
        )
        loaded_lockfile = await Get(LoadedLockfile, LoadedLockfileRequest(chosen_resolve.lockfile))
        pex_native_subsetting_supported = loaded_lockfile.is_pex_native
        if loaded_lockfile.as_constraints_strings:
            requirements = dataclasses.replace(
                requirements,
                constraints_strings=loaded_lockfile.as_constraints_strings,
            )

    should_return_entire_lockfile = (
        python_setup.run_against_entire_lockfile and request.internal_only
    )
    should_request_repository_pex = (
        # The entire lockfile was explicitly requested.
        should_return_entire_lockfile
        # The legacy `resolve_all_constraints`
        or (python_setup.resolve_all_constraints and python_setup.requirement_constraints)
        # A non-PEX-native lockfile was used, and so we cannot directly subset it from a
        # LoadedLockfile.
        or not pex_native_subsetting_supported
    )

    if not should_request_repository_pex:
        if not pex_native_subsetting_supported:
            return requirements, ()

        chosen_resolve = await Get(
            ChosenPythonResolve, ChosenPythonResolveRequest(request.addresses)
        )
        return (
            dataclasses.replace(
                requirements, from_superset=Resolve(chosen_resolve.name, use_entire_lockfile=False)
            ),
            (),
        )

    # Else, request the repository PEX and possibly subset it.
    repository_pex_request = await Get(
        OptionalPexRequest,
        _RepositoryPexRequest(
            request.addresses,
            hardcoded_interpreter_constraints=request.hardcoded_interpreter_constraints,
            platforms=request.platforms,
            complete_platforms=request.complete_platforms,
            internal_only=request.internal_only,
            additional_lockfile_args=request.additional_lockfile_args,
        ),
    )
    if should_return_entire_lockfile:
        if repository_pex_request.maybe_pex_request is None:
            raise ValueError(
                softwrap(
                    f"""
                    [python].run_against_entire_lockfile was set, but could not find a
                    lockfile or constraints file for this target set. See
                    {doc_url('docs/python/overview/third-party-dependencies')} for details.
                    """
                )
            )

    repository_pex = await Get(OptionalPex, OptionalPexRequest, repository_pex_request)
    if should_return_entire_lockfile:
        assert repository_pex_request.maybe_pex_request is not None
        assert repository_pex.maybe_pex is not None
        return repository_pex_request.maybe_pex_request.requirements, [repository_pex.maybe_pex]

    return dataclasses.replace(requirements, from_superset=repository_pex.maybe_pex), ()


async def _warn_about_any_files_targets(
    addresses: Addresses, transitive_targets: TransitiveTargets, union_membership: UnionMembership
) -> None:
    # Warn if users depend on `files` targets, which won't be included in the PEX and is a common
    # gotcha.
    file_tgts = targets_with_sources_types(
        [FileSourceField], transitive_targets.dependencies, union_membership
    )
    if file_tgts:
        # make it easier for the user to find which targets are problematic by including the alias
        targets = await Get(Targets, Addresses, addresses)
        formatted_addresses = ", ".join(
            f"{a} (`{tgt.alias}`)" for a, tgt in zip(addresses, targets)
        )

        files_addresses = sorted(tgt.address.spec for tgt in file_tgts)
        targets_text, depend_text = (
            ("target", "depends") if len(addresses) == 1 else ("targets", "depend")
        )
        logger.warning(
            f"The {targets_text} {formatted_addresses} transitively {depend_text} "
            "on the below `files` targets, but Pants will not include them in the built package. "
            "Filesystem APIs like `open()` may be not able to load files within the binary "
            "itself; instead, they read from the current working directory."
            f"\n\nInstead, use `resources` targets. See {doc_url('resources')}."
            f"\n\nFiles targets dependencies: {files_addresses}"
        )


@rule(level=LogLevel.DEBUG)
async def create_pex_from_targets(
    request: PexFromTargetsRequest,
    python_setup: PythonSetup,
    union_membership: UnionMembership,
) -> PexRequest:
    requirements, additional_pexes = await _determine_requirements_for_pex_from_targets(
        request, python_setup
    )

    interpreter_constraints = await Get(
        InterpreterConstraints,
        InterpreterConstraintsRequest,
        request.to_interpreter_constraints_request(),
    )

    sources_digests = []
    if request.additional_sources:
        sources_digests.append(request.additional_sources)
    if request.include_source_files:
        transitive_targets = await Get(
            TransitiveTargets,
            TransitiveTargetsRequest(
                request.addresses,
                should_traverse_deps_predicate=TraverseIfNotPackageTarget(
                    roots=request.addresses,
                    union_membership=union_membership,
                ),
            ),
        )
        sources = await Get(PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure))

        if request.warn_for_transitive_files_targets:
            await _warn_about_any_files_targets(
                request.addresses, transitive_targets, union_membership
            )
    elif isinstance(request.main, Executable):
        # The source for an --executable main must be embedded in the pex even if not request.include_source_files.
        # If include_source_files is True, the executable source should be included in the (transitive) dependencies.
        description_of_origin = (
            f"The PexFromTargetsRequest with main {request.main} ({request.description})"
        )
        targets = await Get(
            Targets,
            UnparsedAddressInputs(
                [f"//{request.main.spec}"],
                owning_address=None,
                description_of_origin=description_of_origin,
            ),
        )
        sources = await Get(PythonSourceFiles, PythonSourceFilesRequest(targets))
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

    return PexRequest(
        output_filename=request.output_filename,
        internal_only=request.internal_only,
        layout=request.layout,
        requirements=requirements,
        interpreter_constraints=interpreter_constraints,
        platforms=request.platforms,
        complete_platforms=request.complete_platforms,
        main=request.main,
        inject_args=request.inject_args,
        inject_env=request.inject_env,
        sources=merged_sources_digest,
        additional_inputs=additional_inputs,
        additional_args=additional_args,
        description=description,
        pex_path=additional_pexes,
    )


@rule
async def get_repository_pex(
    request: _RepositoryPexRequest, python_setup: PythonSetup
) -> OptionalPexRequest:
    # NB: It isn't safe to resolve against an entire lockfile or constraints file if
    # platforms are in use. See https://github.com/pantsbuild/pants/issues/12222.
    if request.platforms or request.complete_platforms:
        return OptionalPexRequest(None)

    if python_setup.requirement_constraints:
        constraints_repository_pex_request = await Get(
            OptionalPexRequest, _ConstraintsRepositoryPexRequest(request)
        )
        return OptionalPexRequest(constraints_repository_pex_request.maybe_pex_request)

    if not python_setup.enable_resolves:
        return OptionalPexRequest(None)

    chosen_resolve, interpreter_constraints = await MultiGet(
        Get(ChosenPythonResolve, ChosenPythonResolveRequest(request.addresses)),
        Get(
            InterpreterConstraints,
            InterpreterConstraintsRequest,
            request.to_interpreter_constraints_request(),
        ),
    )
    return OptionalPexRequest(
        PexRequest(
            description=softwrap(
                f"""
                Installing {chosen_resolve.lockfile.url} for the resolve
                `{chosen_resolve.name}`
                """
            ),
            output_filename=f"{path_safe(chosen_resolve.name)}_lockfile.pex",
            internal_only=request.internal_only,
            requirements=EntireLockfile(chosen_resolve.lockfile),
            interpreter_constraints=interpreter_constraints,
            layout=PexLayout.PACKED,
            platforms=request.platforms,
            complete_platforms=request.complete_platforms,
            additional_args=request.additional_lockfile_args,
        )
    )


@rule
async def _setup_constraints_repository_pex(
    constraints_request: _ConstraintsRepositoryPexRequest,
    python_setup: PythonSetup,
    global_requirement_constraints: GlobalRequirementConstraints,
) -> OptionalPexRequest:
    request = constraints_request.repository_pex_request
    if not python_setup.resolve_all_constraints:
        return OptionalPexRequest(None)

    constraints_path = python_setup.requirement_constraints
    assert constraints_path is not None

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))

    req_strings = PexRequirements.req_strings_from_requirement_fields(
        tgt[PythonRequirementsField]
        for tgt in transitive_targets.closure
        if tgt.has_field(PythonRequirementsField)
    )

    # In requirement strings, Foo_-Bar.BAZ and foo-bar-baz refer to the same project. We let
    # packaging canonicalize for us.
    # See: https://www.python.org/dev/peps/pep-0503/#normalized-names
    url_reqs = set()  # E.g., 'foobar@ git+https://github.com/foo/bar.git@branch'
    name_reqs = set()  # E.g., foobar>=1.2.3
    name_req_projects = set()
    constraints_file_reqs = set(global_requirement_constraints)

    for req_str in req_strings:
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
            softwrap(
                f"""
                The constraints file {constraints_path} does not contain
                entries for the following requirements: {', '.join(unconstrained_projects)}.

                Ignoring `[python].resolve_all_constraints` option.
                """
            )
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
            description_of_origin=constraints_path,
        ),
        # Monolithic PEXes like the repository PEX should always use the Packed layout.
        layout=PexLayout.PACKED,
        interpreter_constraints=interpreter_constraints,
        platforms=request.platforms,
        complete_platforms=request.complete_platforms,
        additional_args=request.additional_lockfile_args,
    )
    return OptionalPexRequest(repository_pex)


@dataclass(frozen=True)
class RequirementsPexRequest:
    """Requests a PEX containing only thirdparty requirements for internal/non-portable use.

    Used as part of an optimization to reduce the "overhead" (in terms of both time and space) of
    thirdparty requirements by taking advantage of certain PEX features.
    """

    addresses: tuple[Address, ...]
    hardcoded_interpreter_constraints: InterpreterConstraints | None

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        hardcoded_interpreter_constraints: InterpreterConstraints | None = None,
    ) -> None:
        object.__setattr__(self, "addresses", Addresses(addresses))
        object.__setattr__(
            self, "hardcoded_interpreter_constraints", hardcoded_interpreter_constraints
        )


@rule
async def generalize_requirements_pex_request(
    request: RequirementsPexRequest,
) -> PexFromTargetsRequest:
    return PexFromTargetsRequest(
        addresses=sorted(request.addresses),
        output_filename="requirements.pex",
        internal_only=True,
        include_source_files=False,
        hardcoded_interpreter_constraints=request.hardcoded_interpreter_constraints,
    )


def rules():
    return (*collect_rules(), *pex_rules(), *local_dists_rules(), *python_sources_rules())
