# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import functools
import itertools
import logging
import os.path
from collections import deque
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple, Type

from pants.base.exceptions import ResolveError
from pants.base.specs import (
    AddressSpecs,
    AscendantAddresses,
    FilesystemLiteralSpec,
    FilesystemSpecs,
    Specs,
)
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressInput,
    BuildFileAddress,
    UnparsedAddressInputs,
)
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    Digest,
    MergeDigests,
    PathGlobs,
    Paths,
    Snapshot,
    SpecsSnapshot,
)
from pants.engine.internals import native_engine
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    CoarsenedTarget,
    CoarsenedTargets,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    NoApplicableTargetsBehavior,
    RegisteredTargetTypes,
    SecondaryOwnerMixin,
    Sources,
    SourcesPaths,
    SourcesPathsRequest,
    SpecialCasedDependencies,
    Subtargets,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
    UnrecognizedTargetTypeException,
    WrappedTarget,
    generate_subtarget,
    generate_subtarget_address,
)
from pants.engine.unions import UnionMembership
from pants.option.global_options import GlobalOptions, OwnersNotFoundBehavior
from pants.source.filespec import matches_filespec
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Address -> Target(s)
# -----------------------------------------------------------------------------------------------


@rule
async def resolve_unexpanded_targets(addresses: Addresses) -> UnexpandedTargets:
    wrapped_targets = await MultiGet(Get(WrappedTarget, Address, a) for a in addresses)
    return UnexpandedTargets(wrapped_target.target for wrapped_target in wrapped_targets)


@rule
async def generate_subtargets(address: Address) -> Subtargets:
    if address.is_file_target:
        raise ValueError(f"Cannot generate file Targets for a file Address: {address}")
    wrapped_build_target = await Get(WrappedTarget, Address, address)
    build_target = wrapped_build_target.target

    if not build_target.has_field(Dependencies) or not build_target.has_field(Sources):
        # If a target type does not support dependencies, we do not split it, as that would prevent
        # the BUILD target from depending on its splits.
        return Subtargets(build_target, ())

    # Generate a subtarget per source.
    paths = await Get(SourcesPaths, SourcesPathsRequest(build_target[Sources]))
    wrapped_subtargets = await MultiGet(
        Get(
            WrappedTarget,
            Address,
            generate_subtarget_address(address, full_file_name=subtarget_file),
        )
        for subtarget_file in paths.files
    )
    return Subtargets(build_target, tuple(wt.target for wt in wrapped_subtargets))


@rule
async def resolve_target(
    address: Address,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
) -> WrappedTarget:
    if address.is_file_target:
        build_target = await Get(WrappedTarget, Address, address.maybe_convert_to_build_target())
        subtarget = generate_subtarget(
            build_target.target, full_file_name=address.filename, union_membership=union_membership
        )
        return WrappedTarget(subtarget)

    target_adaptor = await Get(TargetAdaptor, Address, address)
    target_type = registered_target_types.aliases_to_types.get(target_adaptor.type_alias, None)
    if target_type is None:
        raise UnrecognizedTargetTypeException(
            target_adaptor.type_alias, registered_target_types, address=address
        )
    target = target_type(target_adaptor.kwargs, address, union_membership=union_membership)
    return WrappedTarget(target)


@rule
async def resolve_targets(targets: UnexpandedTargets) -> Targets:
    # Split out and expand any BUILD targets.
    other_targets = []
    build_targets = []
    for target in targets:
        if not target.address.is_file_target:
            build_targets.append(target)
        else:
            other_targets.append(target)

    build_targets_subtargets = await MultiGet(
        Get(Subtargets, Address, bt.address) for bt in build_targets
    )
    # Zip the subtargets back to the BUILD targets and replace them.
    # NB: If a target had no subtargets, we use the original.
    expanded_targets = OrderedSet(other_targets)
    expanded_targets.update(
        target
        for subtargets in build_targets_subtargets
        for target in (subtargets.subtargets if subtargets.subtargets else (subtargets.base,))
    )
    return Targets(expanded_targets)


# -----------------------------------------------------------------------------------------------
# TransitiveTargets
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _TransitiveTargetRequest(EngineAwareParameter):
    address: Address
    include_special_cased_deps: bool

    def debug_hint(self) -> Optional[str]:
        return str(self.address)


@dataclass(frozen=True)
class _TransitiveTarget:
    """A recursive structure wrapping a Target root and TransitiveTarget deps.

    See `transitive_targets`.
    """

    root: Target
    build_dependencies: Tuple["_TransitiveTarget", ...]
    file_dependencies: Tuple[Address, ...]


@rule
async def transitive_target(request: _TransitiveTargetRequest) -> _TransitiveTarget:
    wrapped_root = await Get(WrappedTarget, Address, request.address)
    root = wrapped_root.target
    if not root.has_field(Dependencies):
        return _TransitiveTarget(root, (), ())

    dependency_targets = await Get(
        UnexpandedTargets,
        DependenciesRequest(
            root.get(Dependencies),
            include_special_cased_deps=request.include_special_cased_deps,
        ),
    )
    build_addresses = []
    file_addresses = []
    for target in dependency_targets:
        if target.address.is_file_target:
            file_addresses.append(target.address)
        else:
            build_addresses.append(target.address)
    build_dependencies = await MultiGet(
        Get(_TransitiveTarget, _TransitiveTargetRequest, dataclasses.replace(request, address=a))
        for a in build_addresses
    )
    return _TransitiveTarget(root, build_dependencies, tuple(file_addresses))


@rule(desc="Resolve transitive targets")
async def transitive_targets(request: TransitiveTargetsRequest) -> TransitiveTargets:
    """Find all the targets transitively depended upon by the target roots.

    This uses a hybrid of structure-shared recursive memoization for BUILD Addresses (which do not
    allow cycles), and iteration for file Addresses (which do allow cycles).

    The TransitiveTarget dataclass represents a structure-shared graph of BUILD (not file)
    dependencies, which we walk and flatten here. The engine memoizes the computation of
    TransitiveTarget, so when multiple TransitiveTargets objects are being constructed for multiple
    roots, their structure will be shared.

    The TransitiveTarget class is consumed by a batch/MultiGet iteration that expands file-
    Addresses, so that those dependencies can tolerate cycles.
    """

    # We immediately flatten the structure-shared BUILD dependencies as they are encountered, and
    # batch expand the file-level dependencies.
    queued = OrderedSet(request.roots)
    visited: OrderedSet[Address] = OrderedSet()
    visited_targets: OrderedSet[Target] = OrderedSet()

    def visit(tts: Iterable[_TransitiveTarget]) -> OrderedSet[Address]:
        file_dependencies: OrderedSet[Address] = OrderedSet()
        to_flatten = deque(tts)
        while to_flatten:
            tt = to_flatten.popleft()
            if tt.root.address in visited:
                continue
            visited.add(tt.root.address)
            visited_targets.add(tt.root)
            to_flatten.extend(tt.build_dependencies)
            file_dependencies.update(a for a in tt.file_dependencies if a not in visited)

        return file_dependencies

    # NB: We visit the roots independently first in order to separate them from their dependencies
    # in the returned TransitiveTargets instance.
    roots = await MultiGet(
        Get(
            _TransitiveTarget,
            _TransitiveTargetRequest(
                address=address, include_special_cased_deps=request.include_special_cased_deps
            ),
        )
        for address in queued
    )
    roots_as_targets = tuple(tt.root for tt in roots)
    queued = visit(d for tt in roots for d in tt.build_dependencies)
    queued.update(a for tt in roots for a in tt.file_dependencies)

    while queued:
        queued = visit(
            await MultiGet(
                Get(
                    _TransitiveTarget,
                    _TransitiveTargetRequest(
                        address=address,
                        include_special_cased_deps=request.include_special_cased_deps,
                    ),
                )
                for address in queued
            )
        )

    # Apply any transitive excludes (`!!` ignores).
    transitive_excludes: FrozenOrderedSet[Target] = FrozenOrderedSet()
    unevaluated_transitive_excludes = []
    for t in (*roots_as_targets, *visited_targets):
        unparsed = t.get(Dependencies).unevaluated_transitive_excludes
        if unparsed.values:
            unevaluated_transitive_excludes.append(unparsed)
    if unevaluated_transitive_excludes:
        nested_transitive_excludes = await MultiGet(
            Get(Targets, UnparsedAddressInputs, unparsed)
            for unparsed in unevaluated_transitive_excludes
        )
        transitive_excludes = FrozenOrderedSet(
            itertools.chain.from_iterable(excludes for excludes in nested_transitive_excludes)
        )

    return TransitiveTargets(
        tuple(roots_as_targets),
        FrozenOrderedSet(visited_targets.difference(transitive_excludes)),
    )


# -----------------------------------------------------------------------------------------------
# CoarsenedTargets
# -----------------------------------------------------------------------------------------------


@rule
async def coarsened_targets(addresses: Addresses) -> CoarsenedTargets:
    # NB: We set include_special_cased_deps=True because although computing CoarsenedTargets
    # requires a transitive graph walk (to ensure that all cycles are actually detected),
    # the resulting CoarsenedTargets instance is not itself transitive: everything not directly
    # involved in a cycle with one of the input Addresses is discarded in the output.
    include_special_cased_deps = True

    # We immediately flatten the structure-shared BUILD dependencies as they are encountered, and
    # batch expand the file-level dependencies.
    mapping: Dict[Address, Tuple[Address, ...]] = {}
    addresses_to_targets: Dict[Address, Target] = {}

    def visit(tts: Iterable[_TransitiveTarget]) -> OrderedSet[Address]:
        file_dependencies: OrderedSet[Address] = OrderedSet()
        to_flatten = deque(tts)
        while to_flatten:
            tt = to_flatten.popleft()
            if tt.root.address in mapping:
                continue
            mapping[tt.root.address] = tuple(
                [*(t.root.address for t in tt.build_dependencies), *tt.file_dependencies]
            )
            addresses_to_targets[tt.root.address] = tt.root

            to_flatten.extend(tt.build_dependencies)
            file_dependencies.update(a for a in tt.file_dependencies if a not in mapping)

        return file_dependencies

    queued = OrderedSet(addresses)
    while queued:
        queued = visit(
            await MultiGet(
                Get(
                    _TransitiveTarget,
                    _TransitiveTargetRequest(
                        address=address,
                        include_special_cased_deps=include_special_cased_deps,
                    ),
                )
                for address in queued
            )
        )

    components = native_engine.strongly_connected_components(list(mapping.items()))

    addresses_set = set(addresses)
    targets = []
    for component in components:
        if not any(component_address in addresses_set for component_address in component):
            continue
        component_set = set(component)
        members = tuple(addresses_to_targets[a] for a in component)
        dependencies = FrozenOrderedSet(
            [d for a in component for d in mapping[a] if d not in component_set]
        )
        targets.append(CoarsenedTarget(members, dependencies))
    return CoarsenedTargets(targets)


# -----------------------------------------------------------------------------------------------
# Find the owners of a file
# -----------------------------------------------------------------------------------------------


class InvalidOwnersOfArgs(Exception):
    pass


@dataclass(frozen=True)
class OwnersRequest:
    """A request for the owners of a set of file paths."""

    sources: Tuple[str, ...]
    owners_not_found_behavior: OwnersNotFoundBehavior = OwnersNotFoundBehavior.ignore


class Owners(Collection[Address]):
    pass


@rule(desc="Find which targets own certain files")
async def find_owners(owners_request: OwnersRequest) -> Owners:
    # Determine which of the sources are live and which are deleted.
    sources_paths = await Get(Paths, PathGlobs(owners_request.sources))

    live_files = FrozenOrderedSet(sources_paths.files)
    deleted_files = FrozenOrderedSet(s for s in owners_request.sources if s not in live_files)
    live_dirs = FrozenOrderedSet(os.path.dirname(s) for s in live_files)
    deleted_dirs = FrozenOrderedSet(os.path.dirname(s) for s in deleted_files)

    # Walk up the buildroot looking for targets that would conceivably claim changed sources.
    # For live files, we use expanded Targets, which have file level precision but which are
    # only created for existing files. For deleted files we use UnexpandedTargets, which have
    # the original declared glob.
    live_candidate_specs = tuple(AscendantAddresses(directory=d) for d in live_dirs)
    deleted_candidate_specs = tuple(AscendantAddresses(directory=d) for d in deleted_dirs)
    live_candidate_tgts, deleted_candidate_tgts = await MultiGet(
        Get(Targets, AddressSpecs(live_candidate_specs)),
        Get(UnexpandedTargets, AddressSpecs(deleted_candidate_specs)),
    )

    matching_addresses: OrderedSet[Address] = OrderedSet()
    unmatched_sources = set(owners_request.sources)
    for live in (True, False):
        candidate_tgts: Sequence[Target]
        if live:
            candidate_tgts = live_candidate_tgts
            sources_set = live_files
        else:
            candidate_tgts = deleted_candidate_tgts
            sources_set = deleted_files

        build_file_addresses = await MultiGet(
            Get(BuildFileAddress, Address, tgt.address) for tgt in candidate_tgts
        )

        for candidate_tgt, bfa in zip(candidate_tgts, build_file_addresses):
            matching_files = set(
                matches_filespec(candidate_tgt.get(Sources).filespec, paths=sources_set)
            )
            # Also consider secondary ownership, meaning it's not a `Sources` field with primary
            # ownership, but the target still should match the file. We can't use `tgt.get()`
            # because this is a mixin, and there technically may be >1 field.
            secondary_owner_fields = tuple(
                field  # type: ignore[misc]
                for field in candidate_tgt.field_values.values()
                if isinstance(field, SecondaryOwnerMixin)
            )
            for secondary_owner_field in secondary_owner_fields:
                matching_files.update(
                    matches_filespec(secondary_owner_field.filespec, paths=sources_set)
                )
            if not matching_files and bfa.rel_path not in sources_set:
                continue

            unmatched_sources -= matching_files
            matching_addresses.add(candidate_tgt.address)

    if (
        unmatched_sources
        and owners_request.owners_not_found_behavior != OwnersNotFoundBehavior.ignore
    ):
        _log_or_raise_unmatched_owners(
            [PurePath(path) for path in unmatched_sources], owners_request.owners_not_found_behavior
        )

    return Owners(matching_addresses)


# -----------------------------------------------------------------------------------------------
# Specs -> Addresses
# -----------------------------------------------------------------------------------------------


def _log_or_raise_unmatched_owners(
    file_paths: Sequence[PurePath],
    owners_not_found_behavior: OwnersNotFoundBehavior,
    ignore_option: Optional[str] = None,
) -> None:
    option_msg = (
        f"\n\nIf you would like to ignore un-owned files, please pass `{ignore_option}`."
        if ignore_option
        else ""
    )
    if len(file_paths) == 1:
        prefix = (
            f"No owning targets could be found for the file `{file_paths[0]}`.\n\n"
            f"Please check that there is a BUILD file in the parent directory "
            f"{file_paths[0].parent} with a target whose `sources` field includes the file."
        )
    else:
        prefix = (
            f"No owning targets could be found for the files {sorted(map(str, file_paths))}`.\n\n"
            f"Please check that there are BUILD files in each file's parent directory with a "
            f"target whose `sources` field includes the file."
        )
    msg = (
        f"{prefix} See {doc_url('targets')} for more information on target definitions."
        f"\n\nYou may want to run `./pants tailor` to autogenerate your BUILD files. See "
        f"{doc_url('create-initial-build-files')}.{option_msg}"
    )

    if owners_not_found_behavior == OwnersNotFoundBehavior.warn:
        logger.warning(msg)
    else:
        raise ResolveError(msg)


@rule
async def addresses_from_filesystem_specs(
    filesystem_specs: FilesystemSpecs, global_options: GlobalOptions
) -> Addresses:
    """Find the owner(s) for each FilesystemSpec.

    Every returned address will be a generated subtarget, meaning that each address will have
    exactly one file in its `sources` field.
    """
    owners_not_found_behavior = global_options.options.owners_not_found_behavior
    paths_per_include = await MultiGet(
        Get(
            Paths,
            PathGlobs,
            filesystem_specs.path_globs_for_spec(
                spec, owners_not_found_behavior.to_glob_match_error_behavior()
            ),
        )
        for spec in filesystem_specs.includes
    )
    owners_per_include = await MultiGet(
        Get(Owners, OwnersRequest(sources=paths.files)) for paths in paths_per_include
    )
    addresses: Set[Address] = set()
    for spec, owners in zip(filesystem_specs.includes, owners_per_include):
        if (
            owners_not_found_behavior != OwnersNotFoundBehavior.ignore
            and isinstance(spec, FilesystemLiteralSpec)
            and not owners
        ):
            _log_or_raise_unmatched_owners(
                [PurePath(str(spec))],
                global_options.options.owners_not_found_behavior,
                ignore_option="--owners-not-found-behavior=ignore",
            )
        addresses.update(owners)
    return Addresses(sorted(addresses))


@rule(desc="Find targets from input specs", level=LogLevel.DEBUG)
async def resolve_addresses_from_specs(specs: Specs) -> Addresses:
    from_address_specs, from_filesystem_specs = await MultiGet(
        Get(Addresses, AddressSpecs, specs.address_specs),
        Get(Addresses, FilesystemSpecs, specs.filesystem_specs),
    )
    # We use a set to dedupe because it's possible to have the same address from both an address
    # and filesystem spec.
    return Addresses(sorted({*from_address_specs, *from_filesystem_specs}))


# -----------------------------------------------------------------------------------------------
# SourcesSnapshot
# -----------------------------------------------------------------------------------------------


@rule(desc="Find all sources from input specs", level=LogLevel.DEBUG)
async def resolve_specs_snapshot(specs: Specs, global_options: GlobalOptions) -> SpecsSnapshot:
    """Resolve all files matching the given specs.

    Address specs will use their `Sources` field, and Filesystem specs will use whatever args were
    given. Filesystem specs may safely refer to files with no owning target.
    """
    targets = await Get(Targets, AddressSpecs, specs.address_specs)
    all_hydrated_sources = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt[Sources]))
        for tgt in targets
        if tgt.has_field(Sources)
    )

    filesystem_specs_digest = (
        await Get(
            Digest,
            PathGlobs,
            specs.filesystem_specs.to_path_globs(
                global_options.options.owners_not_found_behavior.to_glob_match_error_behavior()
            ),
        )
        if specs.filesystem_specs
        else None
    )

    # NB: We merge into a single snapshot to avoid the same files being duplicated if they were
    # covered both by address specs and filesystem specs.
    digests = [hydrated_sources.snapshot.digest for hydrated_sources in all_hydrated_sources]
    if filesystem_specs_digest:
        digests.append(filesystem_specs_digest)
    result = await Get(Snapshot, MergeDigests(digests))
    return SpecsSnapshot(result)


# -----------------------------------------------------------------------------------------------
# Resolve the Sources field
# -----------------------------------------------------------------------------------------------


class AmbiguousCodegenImplementationsException(Exception):
    """Exception for when there are multiple codegen implementations and it is ambiguous which to
    use."""

    def __init__(
        self,
        generators: Iterable[Type["GenerateSourcesRequest"]],
        *,
        for_sources_types: Iterable[Type["Sources"]],
    ) -> None:
        bulleted_list_sep = "\n  * "
        all_same_generator_paths = (
            len(set((generator.input, generator.output) for generator in generators)) == 1
        )
        example_generator = list(generators)[0]
        input = example_generator.input.__name__
        if all_same_generator_paths:
            output = example_generator.output.__name__
            possible_generators = sorted(generator.__name__ for generator in generators)
            super().__init__(
                f"Multiple of the registered code generators can generate {output} from {input}. "
                "It is ambiguous which implementation to use.\n\nPossible implementations:"
                f"{bulleted_list_sep}{bulleted_list_sep.join(possible_generators)}"
            )
        else:
            possible_output_types = sorted(
                generator.output.__name__
                for generator in generators
                if issubclass(generator.output, tuple(for_sources_types))
            )
            possible_generators_with_output = [
                f"{generator.__name__} -> {generator.output.__name__}"
                for generator in sorted(generators, key=lambda generator: generator.output.__name__)
            ]
            super().__init__(
                f"Multiple of the registered code generators can generate one of "
                f"{possible_output_types} from {input}. It is ambiguous which implementation to "
                f"use. This can happen when the call site requests too many different output types "
                f"from the same original protocol sources.\n\nPossible implementations with their "
                f"output type: {bulleted_list_sep}"
                f"{bulleted_list_sep.join(possible_generators_with_output)}"
            )


@rule(desc="Hydrate the `sources` field")
async def hydrate_sources(
    request: HydrateSourcesRequest,
    global_options: GlobalOptions,
    union_membership: UnionMembership,
) -> HydratedSources:
    sources_field = request.field

    # First, find if there are any code generators for the input `sources_field`. This will be used
    # to determine if the sources_field is valid or not.
    # We could alternatively use `sources_field.can_generate()`, but we want to error if there are
    # 2+ generators due to ambiguity.
    generate_request_types = union_membership.get(GenerateSourcesRequest)
    relevant_generate_request_types = [
        generate_request_type
        for generate_request_type in generate_request_types
        if isinstance(sources_field, generate_request_type.input)
        and issubclass(generate_request_type.output, request.for_sources_types)
    ]
    if request.enable_codegen and len(relevant_generate_request_types) > 1:
        raise AmbiguousCodegenImplementationsException(
            relevant_generate_request_types, for_sources_types=request.for_sources_types
        )
    generate_request_type = next(iter(relevant_generate_request_types), None)

    # Now, determine if any of the `for_sources_types` may be used, either because the
    # sources_field is a direct subclass or can be generated into one of the valid types.
    def compatible_with_sources_field(valid_type: Type[Sources]) -> bool:
        is_instance = isinstance(sources_field, valid_type)
        can_be_generated = (
            request.enable_codegen
            and generate_request_type is not None
            and issubclass(generate_request_type.output, valid_type)
        )
        return is_instance or can_be_generated

    sources_type = next(
        (
            valid_type
            for valid_type in request.for_sources_types
            if compatible_with_sources_field(valid_type)
        ),
        None,
    )
    if sources_type is None:
        return HydratedSources(EMPTY_SNAPSHOT, sources_field.filespec, sources_type=None)

    # Now, hydrate the `globs`. Even if we are going to use codegen, we will need the original
    # protocol sources to be hydrated.
    path_globs = sources_field.path_globs(global_options.options.files_not_found_behavior)
    snapshot = await Get(Snapshot, PathGlobs, path_globs)
    sources_field.validate_resolved_files(snapshot.files)

    # Finally, return if codegen is not in use; otherwise, run the relevant code generator.
    if not request.enable_codegen or generate_request_type is None:
        return HydratedSources(snapshot, sources_field.filespec, sources_type=sources_type)
    wrapped_protocol_target = await Get(WrappedTarget, Address, sources_field.address)
    generated_sources = await Get(
        GeneratedSources,
        GenerateSourcesRequest,
        generate_request_type(snapshot, wrapped_protocol_target.target),
    )
    return HydratedSources(
        generated_sources.snapshot, sources_field.filespec, sources_type=sources_type
    )


@rule(desc="Resolve `sources` field file names")
async def resolve_source_paths(
    request: SourcesPathsRequest, global_options: GlobalOptions
) -> SourcesPaths:
    sources_field = request.field
    path_globs = sources_field.path_globs(global_options.options.files_not_found_behavior)
    paths = await Get(Paths, PathGlobs, path_globs)
    sources_field.validate_resolved_files(paths.files)
    return SourcesPaths(files=paths.files, dirs=paths.dirs)


# -----------------------------------------------------------------------------------------------
# Resolve addresses, including the Dependencies field
# -----------------------------------------------------------------------------------------------


class ParsedDependencies(NamedTuple):
    addresses: List[AddressInput]
    ignored_addresses: List[AddressInput]


class TransitiveExcludesNotSupportedError(ValueError):
    def __init__(
        self,
        *,
        bad_value: str,
        address: Address,
        registered_target_types: Sequence[Type[Target]],
        union_membership: UnionMembership,
    ) -> None:
        applicable_target_types = sorted(
            target_type.alias
            for target_type in registered_target_types
            if (
                target_type.class_has_field(Dependencies, union_membership=union_membership)
                and target_type.class_get_field(
                    Dependencies, union_membership=union_membership
                ).supports_transitive_excludes
            )
        )
        super().__init__(
            f"Bad value '{bad_value}' in the `dependencies` field for {address}. "
            "Transitive excludes with `!!` are not supported for this target type. Did you mean "
            "to use a single `!` for a direct exclude?\n\nTransitive excludes work with these "
            f"target types: {applicable_target_types}"
        )


@rule
async def determine_explicitly_provided_dependencies(
    request: DependenciesRequest,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
    global_options: GlobalOptions,
) -> ExplicitlyProvidedDependencies:
    parse = functools.partial(
        AddressInput.parse,
        relative_to=request.field.address.spec_path,
        subproject_roots=global_options.options.subproject_roots,
    )

    addresses: List[AddressInput] = []
    ignored_addresses: List[AddressInput] = []
    for v in request.field.value or ():
        is_ignore = v.startswith("!")
        if is_ignore:
            # Check if it's a transitive exclude, rather than a direct exclude.
            if v.startswith("!!"):
                if not request.field.supports_transitive_excludes:
                    raise TransitiveExcludesNotSupportedError(
                        bad_value=v,
                        address=request.field.address,
                        registered_target_types=registered_target_types.types,
                        union_membership=union_membership,
                    )
                v = v[2:]
            else:
                v = v[1:]
        result = parse(v)
        if is_ignore:
            ignored_addresses.append(result)
        else:
            addresses.append(result)

    parsed_includes = await MultiGet(Get(Address, AddressInput, ai) for ai in addresses)
    parsed_ignores = await MultiGet(Get(Address, AddressInput, ai) for ai in ignored_addresses)
    return ExplicitlyProvidedDependencies(
        request.field.address,
        FrozenOrderedSet(sorted(parsed_includes)),
        FrozenOrderedSet(sorted(parsed_ignores)),
    )


@rule(desc="Resolve direct dependencies")
async def resolve_dependencies(
    request: DependenciesRequest, union_membership: UnionMembership, global_options: GlobalOptions
) -> Addresses:
    explicitly_provided = await Get(ExplicitlyProvidedDependencies, DependenciesRequest, request)

    # Inject any dependencies. This is determined by the `request.field` class. For example, if
    # there is a rule to inject for FortranDependencies, then FortranDependencies and any subclass
    # of FortranDependencies will use that rule.
    inject_request_types = union_membership.get(InjectDependenciesRequest)
    injected = await MultiGet(
        Get(InjectedDependencies, InjectDependenciesRequest, inject_request_type(request.field))
        for inject_request_type in inject_request_types
        if isinstance(request.field, inject_request_type.inject_for)
    )

    inference_request_types = union_membership.get(InferDependenciesRequest)
    inferred: Tuple[InferredDependencies, ...] = ()
    if inference_request_types:
        # Dependency inference is solely determined by the `Sources` field for a Target, so we
        # re-resolve the original target to inspect its `Sources` field, if any.
        wrapped_tgt = await Get(WrappedTarget, Address, request.field.address)
        sources_field = wrapped_tgt.target.get(Sources)
        relevant_inference_request_types = [
            inference_request_type
            for inference_request_type in inference_request_types
            if isinstance(sources_field, inference_request_type.infer_from)
        ]
        inferred = await MultiGet(
            Get(
                InferredDependencies,
                InferDependenciesRequest,
                inference_request_type(sources_field),
            )
            for inference_request_type in relevant_inference_request_types
        )

    # If this is a BUILD target, or no dependency inference implementation can infer dependencies on
    # a file address's sibling files, then we inject dependencies on all the BUILD target's
    # generated subtargets.
    subtarget_addresses: Tuple[Address, ...] = ()
    no_sibling_file_deps_inferrable = not inferred or all(
        inferred_deps.sibling_dependencies_inferrable is False for inferred_deps in inferred
    )
    if not request.field.address.is_file_target or no_sibling_file_deps_inferrable:
        subtargets = await Get(
            Subtargets, Address, request.field.address.maybe_convert_to_build_target()
        )
        subtarget_addresses = tuple(
            t.address for t in subtargets.subtargets if t.address != request.field.address
        )

    # If the target has `SpecialCasedDependencies`, such as the `archive` target having
    # `files` and `packages` fields, then we possibly include those too. We don't want to always
    # include those dependencies because they should often be excluded from the result due to
    # being handled elsewhere in the calling code.
    special_cased: Tuple[Address, ...] = ()
    if request.include_special_cased_deps:
        wrapped_tgt = await Get(WrappedTarget, Address, request.field.address)
        # Unlike normal, we don't use `tgt.get()` because there may be >1 subclass of
        # SpecialCasedDependencies.
        special_cased_fields = tuple(
            field
            for field in wrapped_tgt.target.field_values.values()
            if isinstance(field, SpecialCasedDependencies)
        )
        # We can't use the normal `Get(Addresses, UnparsedAddressInputs)` due to a graph cycle.
        special_cased = await MultiGet(
            Get(
                Address,
                AddressInput,
                AddressInput.parse(
                    addr,
                    relative_to=request.field.address.spec_path,
                    subproject_roots=global_options.options.subproject_roots,
                ),
            )
            for special_cased_field in special_cased_fields
            for addr in special_cased_field.to_unparsed_address_inputs().values
        )

    result = {
        addr
        for addr in (
            *subtarget_addresses,
            *explicitly_provided.includes,
            *itertools.chain.from_iterable(injected),
            *itertools.chain.from_iterable(inferred),
            *special_cased,
        )
        if addr not in explicitly_provided.ignores
    }
    return Addresses(sorted(result))


@rule(desc="Resolve addresses")
async def resolve_unparsed_address_inputs(
    request: UnparsedAddressInputs, global_options: GlobalOptions
) -> Addresses:
    addresses = await MultiGet(
        Get(
            Address,
            AddressInput,
            AddressInput.parse(
                v,
                relative_to=request.relative_to,
                subproject_roots=global_options.options.subproject_roots,
            ),
        )
        for v in request.values
    )
    return Addresses(addresses)


# -----------------------------------------------------------------------------------------------
# Find applicable field sets
# -----------------------------------------------------------------------------------------------


class NoApplicableTargetsException(Exception):
    def __init__(
        self,
        targets: Iterable[Target],
        specs: Specs,
        union_membership: UnionMembership,
        *,
        applicable_target_types: Iterable[Type[Target]],
        goal_description: str,
    ) -> None:
        applicable_target_aliases = sorted(
            {target_type.alias for target_type in applicable_target_types}
        )
        inapplicable_target_aliases = sorted({tgt.alias for tgt in targets})
        bulleted_list_sep = "\n  * "

        msg = (
            "No applicable files or targets matched."
            if inapplicable_target_aliases
            else "No files or targets specified."
        )
        msg += (
            f" {goal_description.capitalize()} works "
            f"with these target types:\n{bulleted_list_sep}"
            f"{bulleted_list_sep.join(applicable_target_aliases)}\n\n"
        )

        # Explain what was specified, if relevant.
        if inapplicable_target_aliases:
            if bool(specs.filesystem_specs) and bool(specs.address_specs):
                specs_description = " files and targets with "
            elif bool(specs.filesystem_specs):
                specs_description = " files with "
            elif bool(specs.address_specs):
                specs_description = " targets with "
            else:
                specs_description = " "
            msg += (
                f"However, you only specified{specs_description}these target types:\n"
                f"{bulleted_list_sep}{bulleted_list_sep.join(inapplicable_target_aliases)}\n\n"
            )

        # Add a remedy.
        #
        # We sometimes suggest using `./pants filedeps` to find applicable files. However, this
        # command only works if at least one of the targets has a Sources field.
        #
        # NB: Even with the "secondary owners" mechanism - used by target types like `pex_binary`
        # and `python_awslambda` to still work with file args - those targets will not show the
        # associated files when using filedeps.
        filedeps_goal_works = any(
            tgt.class_has_field(Sources, union_membership) for tgt in applicable_target_types
        )
        pants_filter_command = (
            f"./pants filter --target-type={','.join(applicable_target_aliases)} ::"
        )
        remedy = (
            f"Please specify relevant files and/or targets. Run `{pants_filter_command}` to "
            "find all applicable targets in your project"
        )
        if filedeps_goal_works:
            remedy += (
                f", or run `{pants_filter_command} | xargs ./pants filedeps` to find all "
                "applicable files."
            )
        else:
            remedy += "."
        msg += remedy
        super().__init__(msg)

    @classmethod
    def create_from_field_sets(
        cls,
        targets: Iterable[Target],
        specs: Specs,
        union_membership: UnionMembership,
        registered_target_types: RegisteredTargetTypes,
        *,
        field_set_types: Iterable[type[FieldSet]],
        goal_description: str,
    ) -> NoApplicableTargetsException:
        applicable_target_types = {
            target_type
            for field_set_type in field_set_types
            for target_type in field_set_type.applicable_target_types(
                registered_target_types.types, union_membership
            )
        }
        return cls(
            targets,
            specs,
            union_membership,
            applicable_target_types=applicable_target_types,
            goal_description=goal_description,
        )


class TooManyTargetsException(Exception):
    def __init__(self, targets: Iterable[Target], *, goal_description: str) -> None:
        bulleted_list_sep = "\n  * "
        addresses = sorted(tgt.address.spec for tgt in targets)
        super().__init__(
            f"{goal_description.capitalize()} only works with one valid target, but was given "
            f"multiple valid targets:{bulleted_list_sep}{bulleted_list_sep.join(addresses)}\n\n"
            "Please select one of these targets to run."
        )


class AmbiguousImplementationsException(Exception):
    """A target has multiple valid FieldSets, but a goal expects there to be one FieldSet."""

    def __init__(
        self,
        target: Target,
        field_sets: Iterable[FieldSet],
        *,
        goal_description: str,
    ) -> None:
        # TODO: improve this error message. A better error message would explain to users how they
        #  can resolve the issue.
        possible_field_sets_types = sorted(field_set.__class__.__name__ for field_set in field_sets)
        bulleted_list_sep = "\n  * "
        super().__init__(
            f"Multiple of the registered implementations for {goal_description} work for "
            f"{target.address} (target type {repr(target.alias)}). It is ambiguous which "
            "implementation to use.\n\nPossible implementations:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(possible_field_sets_types)}"
        )


@rule
async def find_valid_field_sets_for_target_roots(
    request: TargetRootsToFieldSetsRequest,
    specs: Specs,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
) -> TargetRootsToFieldSets:
    # NB: This must be in an `await Get`, rather than the rule signature, to avoid a rule graph
    # issue.
    targets = await Get(Targets, Specs, specs)
    field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(request.field_set_superclass, targets)
    )
    targets_to_applicable_field_sets = {}
    for tgt, field_sets in zip(targets, field_sets_per_target.collection):
        if field_sets:
            targets_to_applicable_field_sets[tgt] = field_sets

    # Possibly warn or error if no targets were applicable.
    if not targets_to_applicable_field_sets:
        no_applicable_exception = NoApplicableTargetsException.create_from_field_sets(
            targets,
            specs,
            union_membership,
            registered_target_types,
            field_set_types=union_membership[request.field_set_superclass],
            goal_description=request.goal_description,
        )
        if request.no_applicable_targets_behavior == NoApplicableTargetsBehavior.error:
            raise no_applicable_exception
        if request.no_applicable_targets_behavior == NoApplicableTargetsBehavior.warn:
            logger.warning(str(no_applicable_exception))

    result = TargetRootsToFieldSets(targets_to_applicable_field_sets)
    if not request.expect_single_field_set:
        return result
    if len(result.targets) > 1:
        raise TooManyTargetsException(result.targets, goal_description=request.goal_description)
    if len(result.field_sets) > 1:
        raise AmbiguousImplementationsException(
            result.targets[0], result.field_sets, goal_description=request.goal_description
        )
    return result


@rule
def find_valid_field_sets(
    request: FieldSetsPerTargetRequest, union_membership: UnionMembership
) -> FieldSetsPerTarget:
    field_set_types = union_membership.get(request.field_set_superclass)
    return FieldSetsPerTarget(
        (
            field_set_type.create(target)
            for field_set_type in field_set_types
            if field_set_type.is_applicable(target)
        )
        for target in request.targets
    )


def rules():
    return collect_rules()
