# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import itertools
import logging
import os.path
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple, Type, Union

from pants.base.exceptions import ResolveError
from pants.base.specs import (
    AddressSpecs,
    AscendantAddresses,
    FilesystemLiteralSpec,
    FilesystemSpec,
    FilesystemSpecs,
    Specs,
)
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressesWithOrigins,
    AddressInput,
    AddressWithOrigin,
    BuildFileAddress,
)
from pants.engine.collection import Collection
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    Digest,
    MergeDigests,
    PathGlobs,
    Snapshot,
    SourcesSnapshot,
)
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, MultiGet, RootRule, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
    FieldSetWithOrigin,
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    RegisteredTargetTypes,
    Sources,
    Subtargets,
    Target,
    Targets,
    TargetsToValidFieldSets,
    TargetsToValidFieldSetsRequest,
    TargetsWithOrigins,
    TargetWithOrigin,
    TransitiveTargets,
    UnexpandedTargets,
    UnexpandedTargetsWithOrigins,
    UnrecognizedTargetTypeException,
    WrappedTarget,
    _AbstractFieldSet,
    generate_subtarget,
    generate_subtarget_address,
)
from pants.engine.unions import UnionMembership
from pants.option.global_options import GlobalOptions, OwnersNotFoundBehavior
from pants.source.filespec import matches_filespec
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Address -> Target(s)
# -----------------------------------------------------------------------------------------------


@rule
async def generate_subtargets(address: Address, global_options: GlobalOptions) -> Subtargets:
    if not address.is_base_target:
        raise ValueError(f"Cannot generate file Targets for a file Address: {address}")
    wrapped_base_target = await Get(WrappedTarget, Address, address)
    base_target = wrapped_base_target.target

    if not base_target.has_field(Dependencies) or not base_target.has_field(Sources):
        # If a target type does not support dependencies, we do not split it, as that would prevent
        # the base target from depending on its splits.
        return Subtargets(base_target, ())

    # Create subtargets for matched sources.
    sources_field = base_target[Sources]
    sources_field_path_globs = sources_field.path_globs(
        global_options.options.files_not_found_behavior
    )
    if sources_field_path_globs is None:
        return Subtargets(base_target, ())

    # Generate a subtarget per source.
    snapshot = await Get(Snapshot, PathGlobs, sources_field_path_globs)
    sources_field.validate_snapshot(snapshot)
    wrapped_subtargets = await MultiGet(
        Get(
            WrappedTarget,
            Address,
            generate_subtarget_address(address, full_file_name=subtarget_file),
        )
        for subtarget_file in snapshot.files
    )

    return Subtargets(base_target, tuple(wt.target for wt in wrapped_subtargets))


@rule
async def resolve_target(
    address: Address,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
) -> WrappedTarget:
    if not address.is_base_target:
        base_target = await Get(WrappedTarget, Address, address.maybe_convert_to_base_target())
        subtarget = generate_subtarget(
            base_target.target, full_file_name=address.filename, union_membership=union_membership
        )
        return WrappedTarget(subtarget)

    target_adaptor = await Get(TargetAdaptor, Address, address)
    target_type = registered_target_types.aliases_to_types.get(target_adaptor.type_alias, None)
    if target_type is None:
        raise UnrecognizedTargetTypeException(
            target_adaptor.type_alias, registered_target_types, address=address
        )
    target = target_type(target_adaptor.kwargs, address=address, union_membership=union_membership)
    return WrappedTarget(target)


@rule
async def resolve_targets(targets: UnexpandedTargets) -> Targets:
    # TODO: This method duplicates `resolve_targets_with_origins`, because direct expansion of
    # `Addresses` to `Targets` is common in a few places: we can't always assume that we
    # have `AddressesWithOrigins`. One way to dedupe these two methods would be to fake some
    # origins, and then strip them afterward.

    # Split out and expand any base targets.
    # TODO: Should recursively expand alias targets here as well.
    other_targets = []
    base_targets = []
    for target in targets:
        if target.address.is_base_target:
            base_targets.append(target)
        else:
            other_targets.append(target)

    base_targets_subtargets = await MultiGet(
        Get(Subtargets, Address, bt.address) for bt in base_targets
    )
    # Zip the subtargets back to the base targets and replace them.
    # NB: If a target had no subtargets, we use the base.
    expanded_targets = OrderedSet(other_targets)
    expanded_targets.update(
        target
        for subtargets in base_targets_subtargets
        for target in (subtargets.subtargets if subtargets.subtargets else (subtargets.base,))
    )
    return Targets(expanded_targets)


@rule
async def resolve_unexpanded_targets(addresses: Addresses) -> UnexpandedTargets:
    wrapped_targets = await MultiGet(Get(WrappedTarget, Address, a) for a in addresses)
    return UnexpandedTargets(wrapped_target.target for wrapped_target in wrapped_targets)


# -----------------------------------------------------------------------------------------------
# AddressWithOrigin(s) -> TargetWithOrigin(s)
# -----------------------------------------------------------------------------------------------


@rule
async def resolve_target_with_origin(address_with_origin: AddressWithOrigin) -> TargetWithOrigin:
    wrapped_target = await Get(WrappedTarget, Address, address_with_origin.address)
    return TargetWithOrigin(wrapped_target.target, address_with_origin.origin)


@rule
async def resolve_targets_with_origins(
    addresses_with_origins: AddressesWithOrigins,
) -> TargetsWithOrigins:
    # TODO: See `resolve_targets`.
    targets_with_origins = await MultiGet(
        Get(TargetWithOrigin, AddressWithOrigin, address_with_origin)
        for address_with_origin in addresses_with_origins
    )
    # Split out and expand any base targets.
    # TODO: Should recursively expand alias targets here as well.
    other_targets_with_origins = []
    base_targets_with_origins = []
    for to in targets_with_origins:
        if to.target.address.is_base_target:
            base_targets_with_origins.append(to)
        else:
            other_targets_with_origins.append(to)

    base_targets_subtargets = await MultiGet(
        Get(Subtargets, Address, to.target.address) for to in base_targets_with_origins
    )
    # Zip the subtargets back to the base targets and replace them while maintaining origins.
    # NB: If a target had no subtargets, we use the base.
    expanded_targets_with_origins = set(other_targets_with_origins)
    expanded_targets_with_origins.update(
        TargetWithOrigin(target, bto.origin)
        for bto, subtargets in zip(base_targets_with_origins, base_targets_subtargets)
        for target in (subtargets.subtargets if subtargets.subtargets else [bto.target])
    )
    return TargetsWithOrigins(expanded_targets_with_origins)


@rule
async def resolve_unexpanded_targets_with_origins(
    addresses_with_origins: AddressesWithOrigins,
) -> UnexpandedTargetsWithOrigins:
    targets_with_origins = await MultiGet(
        Get(TargetWithOrigin, AddressWithOrigin, address_with_origin)
        for address_with_origin in addresses_with_origins
    )
    return UnexpandedTargetsWithOrigins(targets_with_origins)


# -----------------------------------------------------------------------------------------------
# TransitiveTargets
# -----------------------------------------------------------------------------------------------


class CycleException(Exception):
    def __init__(self, subject: Address, path: Tuple[Address, ...]) -> None:
        path_string = "\n".join((f"-> {a}" if a == subject else f"   {a}") for a in path)
        super().__init__(f"Dependency graph contained a cycle:\n{path_string}")
        self.subject = subject
        self.path = path


def _detect_cycles(
    roots: Tuple[Address, ...], dependency_mapping: Dict[Address, Tuple[Address, ...]]
) -> None:
    path_stack: OrderedSet[Address] = OrderedSet()
    visited: Set[Address] = set()

    def maybe_report_cycle(address: Address) -> None:
        # NB: File-level dependencies are cycle tolerant.
        if not address.is_base_target or address not in path_stack:
            return

        # The path of the cycle is shorter than the entire path to the cycle: if the suffix of
        # the path representing the cycle contains a file dep, it is ignored.
        in_cycle = False
        for path_address in path_stack:
            if in_cycle and not path_address.is_base_target:
                # There is a file address inside the cycle: do not report it.
                return
            elif in_cycle:
                # Not a file address.
                continue
            else:
                # We're entering the suffix of the path that contains the cycle if we've reached
                # the address in question.
                in_cycle = path_address == address
        # If we did not break out early, it's because there were no file addresses in the cycle.
        raise CycleException(address, (*path_stack, address))

    def visit(address: Address):
        if address in visited:
            maybe_report_cycle(address)
            return
        path_stack.add(address)
        visited.add(address)

        for dep_address in dependency_mapping[address]:
            visit(dep_address)

        path_stack.remove(address)

    for root in roots:
        visit(root)
        if path_stack:
            raise AssertionError(
                f"The stack of visited nodes should have been empty at the end of recursion, "
                f"but it still contained: {path_stack}"
            )


@rule
async def transitive_targets(targets: Targets) -> TransitiveTargets:
    """Find all the targets transitively depended upon by the target roots.

    This uses iteration, rather than recursion, so that we can tolerate dependency cycles. Unlike a
    traditional BFS algorithm, we batch each round of traversals via `MultiGet` for improved
    performance / concurrency.
    """
    visited: OrderedSet[Target] = OrderedSet()
    queued = FrozenOrderedSet(targets)
    dependency_mapping: Dict[Address, Tuple[Address, ...]] = {}
    while queued:
        direct_dependencies = await MultiGet(
            Get(Targets, DependenciesRequest(tgt.get(Dependencies))) for tgt in queued
        )

        dependency_mapping.update(
            zip(
                (t.address for t in queued),
                (tuple(t.address for t in deps) for deps in direct_dependencies),
            )
        )

        queued = FrozenOrderedSet(itertools.chain.from_iterable(direct_dependencies)).difference(
            visited
        )
        visited.update(queued)

    _detect_cycles(tuple(t.address for t in targets), dependency_mapping)

    transitive_wrapped_excludes = await MultiGet(
        Get(WrappedTarget, AddressInput, address_input)
        for t in (*targets, *visited)
        for address_input in t.get(Dependencies).unevaluated_transitive_excludes
    )
    transitive_excludes = FrozenOrderedSet(
        wrapped_t.target for wrapped_t in transitive_wrapped_excludes
    )

    return TransitiveTargets(
        tuple(targets), FrozenOrderedSet(visited.difference(transitive_excludes))
    )


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


@rule
async def find_owners(owners_request: OwnersRequest) -> Owners:
    # Determine which of the sources are live and which are deleted.
    sources_set_snapshot = await Get(Snapshot, PathGlobs(owners_request.sources))

    live_files = FrozenOrderedSet(sources_set_snapshot.files)
    deleted_files = FrozenOrderedSet(s for s in owners_request.sources if s not in live_files)
    live_dirs = FrozenOrderedSet(os.path.dirname(s) for s in live_files)
    deleted_dirs = FrozenOrderedSet(os.path.dirname(s) for s in deleted_files)

    matching_addresses: OrderedSet[Address] = OrderedSet()
    unmatched_sources = set(owners_request.sources)
    for live in (True, False):
        # Walk up the buildroot looking for targets that would conceivably claim changed sources.
        # For live files, we use expanded Targets, which have file level precision but which are
        # only created for existing files. For deleted files we use UnexpandedTargets, which have
        # the original declared glob.
        candidate_targets: Iterable[Target]
        if live:
            if not live_dirs:
                continue
            sources_set = live_files
            candidate_specs = tuple(AscendantAddresses(directory=d) for d in live_dirs)
            candidate_targets = await Get(Targets, AddressSpecs(candidate_specs))
        else:
            if not deleted_dirs:
                continue
            sources_set = deleted_files
            candidate_specs = tuple(AscendantAddresses(directory=d) for d in deleted_dirs)
            candidate_targets = await Get(UnexpandedTargets, AddressSpecs(candidate_specs))

        build_file_addresses = await MultiGet(
            Get(BuildFileAddress, Address, tgt.address) for tgt in candidate_targets
        )

        for candidate_tgt, bfa in zip(candidate_targets, build_file_addresses):
            matching_files = set(
                matches_filespec(candidate_tgt.get(Sources).filespec, paths=sources_set)
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
    msgs = []
    if ignore_option:
        option_msg = f"\nIf you would like to ignore un-owned files, please pass `{ignore_option}`."
    else:
        option_msg = ""
    for file_path in file_paths:
        msgs.append(
            f"No owning targets could be found for the file `{file_path}`.\n\nPlease check "
            f"that there is a BUILD file in `{file_path.parent}` with a target whose `sources` "
            f"field includes `{file_path}`. See https://www.pantsbuild.org/docs/targets for more "
            f"information on target definitions.{option_msg}"
        )

    if owners_not_found_behavior == OwnersNotFoundBehavior.warn:
        for msg in msgs:
            logger.warning(msg)
    else:
        raise ResolveError("\n\n".join(msgs))


@rule
async def addresses_with_origins_from_filesystem_specs(
    filesystem_specs: FilesystemSpecs, global_options: GlobalOptions,
) -> AddressesWithOrigins:
    """Find the owner(s) for each FilesystemSpec while preserving the original FilesystemSpec those
    owners come from.

    Every returned address will be a generated subtarget, meaning that each address will have
    exactly one file in its `sources` field.
    """
    owners_not_found_behavior = global_options.options.owners_not_found_behavior
    snapshot_per_include = await MultiGet(
        Get(
            Snapshot,
            PathGlobs,
            filesystem_specs.path_globs_for_spec(
                spec, owners_not_found_behavior.to_glob_match_error_behavior()
            ),
        )
        for spec in filesystem_specs.includes
    )
    owners_per_include = await MultiGet(
        Get(Owners, OwnersRequest(sources=snapshot.files)) for snapshot in snapshot_per_include
    )
    addresses_to_specs: Dict[Address, FilesystemSpec] = {}
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
        for address in owners:
            # A target might be covered by multiple specs, so we take the most specific one.
            addresses_to_specs[address] = FilesystemSpecs.more_specific(
                addresses_to_specs.get(address), spec
            )
    return AddressesWithOrigins(
        AddressWithOrigin(address, spec) for address, spec in addresses_to_specs.items()
    )


@rule(desc="Find targets from input specs", level=LogLevel.DEBUG)
async def resolve_addresses_with_origins(specs: Specs) -> AddressesWithOrigins:
    from_address_specs, from_filesystem_specs = await MultiGet(
        Get(AddressesWithOrigins, AddressSpecs, specs.address_specs),
        Get(AddressesWithOrigins, FilesystemSpecs, specs.filesystem_specs),
    )
    # It's possible to resolve the same address both with filesystem specs and address specs. We
    # dedupe, but must go through some ceremony for the equality check because the OriginSpec will
    # differ.
    address_spec_addresses = FrozenOrderedSet(awo.address for awo in from_address_specs)
    return AddressesWithOrigins(
        (
            *from_address_specs,
            *(awo for awo in from_filesystem_specs if awo.address not in address_spec_addresses),
        )
    )


# -----------------------------------------------------------------------------------------------
# SourcesSnapshot
# -----------------------------------------------------------------------------------------------


@rule(desc="Find all sources from input specs", level=LogLevel.DEBUG)
async def resolve_sources_snapshot(specs: Specs, global_options: GlobalOptions) -> SourcesSnapshot:
    """Request a snapshot for the given specs.

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
    return SourcesSnapshot(result)


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


@rule
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
    if path_globs is None:
        return HydratedSources(EMPTY_SNAPSHOT, sources_field.filespec, sources_type=sources_type)
    snapshot = await Get(Snapshot, PathGlobs, path_globs)
    sources_field.validate_snapshot(snapshot)

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


# -----------------------------------------------------------------------------------------------
# Resolve the Dependencies field
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
        valid_target_types = sorted(
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
            f"target types: {valid_target_types}"
        )


def parse_dependencies_field(
    field: Dependencies,
    *,
    subproject_roots: Sequence[str],
    registered_target_types: Sequence[Type[Target]],
    union_membership: UnionMembership,
) -> ParsedDependencies:
    parse = functools.partial(
        AddressInput.parse, relative_to=field.address.spec_path, subproject_roots=subproject_roots
    )

    addresses: List[AddressInput] = []
    ignored_addresses: List[AddressInput] = []
    for v in field.sanitized_raw_value or ():
        is_ignore = v.startswith("!")
        if is_ignore:
            # Check if it's a transitive exclude, rather than a direct exclude.
            if v.startswith("!!"):
                if not field.supports_transitive_excludes:
                    raise TransitiveExcludesNotSupportedError(
                        bad_value=v,
                        address=field.address,
                        registered_target_types=registered_target_types,
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
    return ParsedDependencies(addresses, ignored_addresses)


@rule
async def resolve_dependencies(
    request: DependenciesRequest,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
    global_options: GlobalOptions,
) -> Addresses:
    provided = parse_dependencies_field(
        request.field,
        subproject_roots=global_options.options.subproject_roots,
        registered_target_types=registered_target_types.types,
        union_membership=union_membership,
    )
    literal_addresses = await MultiGet(Get(Address, AddressInput, ai) for ai in provided.addresses)
    ignored_addresses = set(
        await MultiGet(Get(Address, AddressInput, ai) for ai in provided.ignored_addresses)
    )

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

    # If this is a base target, or no dependency inference implementation can infer dependencies on
    # a file address's sibling files, then we inject dependencies on all the base target's
    # generated subtargets.
    subtarget_addresses: Tuple[Address, ...] = ()
    no_sibling_file_deps_inferrable = not inferred or all(
        inferred_deps.sibling_dependencies_inferrable is False for inferred_deps in inferred
    )
    if request.field.address.is_base_target or no_sibling_file_deps_inferrable:
        subtargets = await Get(
            Subtargets, Address, request.field.address.maybe_convert_to_base_target()
        )
        subtarget_addresses = tuple(
            t.address for t in subtargets.subtargets if t.address != request.field.address
        )

    result = {
        addr
        for addr in (
            *subtarget_addresses,
            *literal_addresses,
            *itertools.chain.from_iterable(injected),
            *itertools.chain.from_iterable(inferred),
        )
        if addr not in ignored_addresses
    }
    return Addresses(sorted(result))


# -----------------------------------------------------------------------------------------------
# Find valid field sets
# -----------------------------------------------------------------------------------------------


class NoValidTargetsException(Exception):
    def __init__(
        self,
        targets_with_origins: TargetsWithOrigins,
        *,
        valid_target_types: Iterable[Type[Target]],
        goal_description: str,
    ) -> None:
        valid_target_aliases = sorted({target_type.alias for target_type in valid_target_types})
        invalid_target_aliases = sorted({tgt.alias for tgt in targets_with_origins.targets})
        specs = sorted(
            {str(target_with_origin.origin) for target_with_origin in targets_with_origins}
        )
        bulleted_list_sep = "\n  * "
        super().__init__(
            f"{goal_description.capitalize()} only works with the following target types:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(valid_target_aliases)}\n\n"
            f"You specified `{' '.join(specs)}`, which only included the following target types:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(invalid_target_aliases)}"
        )

    @classmethod
    def create_from_field_sets(
        cls,
        targets_with_origins: TargetsWithOrigins,
        *,
        field_set_types: Iterable[Type[_AbstractFieldSet]],
        goal_description: str,
        union_membership: UnionMembership,
        registered_target_types: RegisteredTargetTypes,
    ) -> "NoValidTargetsException":
        valid_target_types = {
            target_type
            for field_set_type in field_set_types
            for target_type in field_set_type.valid_target_types(
                registered_target_types.types, union_membership=union_membership
            )
        }
        return cls(
            targets_with_origins,
            valid_target_types=valid_target_types,
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
    """Exception for when a single target has multiple valid FieldSets, but the goal only expects
    there to be one FieldSet."""

    def __init__(
        self, target: Target, field_sets: Iterable[_AbstractFieldSet], *, goal_description: str,
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
def find_valid_field_sets(
    request: TargetsToValidFieldSetsRequest,
    targets_with_origins: TargetsWithOrigins,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
) -> TargetsToValidFieldSets:
    field_set_types: Iterable[
        Union[Type[FieldSet], Type[FieldSetWithOrigin]]
    ] = union_membership.union_rules[request.field_set_superclass]
    targets_to_valid_field_sets = {}
    for tgt_with_origin in targets_with_origins:
        valid_field_sets = [
            (
                field_set_type.create(tgt_with_origin)
                if issubclass(field_set_type, FieldSetWithOrigin)
                else field_set_type.create(tgt_with_origin.target)
            )
            for field_set_type in field_set_types
            if field_set_type.is_valid(tgt_with_origin.target)
        ]
        if valid_field_sets:
            targets_to_valid_field_sets[tgt_with_origin] = valid_field_sets
    if request.error_if_no_valid_targets and not targets_to_valid_field_sets:
        raise NoValidTargetsException.create_from_field_sets(
            TargetsWithOrigins(targets_with_origins),
            field_set_types=field_set_types,
            goal_description=request.goal_description,
            union_membership=union_membership,
            registered_target_types=registered_target_types,
        )
    result = TargetsToValidFieldSets(targets_to_valid_field_sets)
    if not request.expect_single_field_set:
        return result
    if len(result.targets) > 1:
        raise TooManyTargetsException(result.targets, goal_description=request.goal_description)
    if len(result.field_sets) > 1:
        raise AmbiguousImplementationsException(
            result.targets[0], result.field_sets, goal_description=request.goal_description
        )
    return result


def rules():
    return [
        *collect_rules(),
        RootRule(DependenciesRequest),
        RootRule(HydrateSourcesRequest),
        RootRule(InferDependenciesRequest),
        RootRule(InjectDependenciesRequest),
        RootRule(OwnersRequest),
        RootRule(Specs),
        RootRule(TargetsToValidFieldSetsRequest),
    ]
