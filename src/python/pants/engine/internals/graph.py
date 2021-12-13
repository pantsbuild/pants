# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import itertools
import logging
import os.path
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, NamedTuple, Sequence, cast

from pants.base.deprecated import warn_or_error
from pants.base.exceptions import ResolveError
from pants.base.specs import (
    AddressSpecs,
    AscendantAddresses,
    FileLiteralSpec,
    FilesystemSpecs,
    MaybeEmptyDescendantAddresses,
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
    AllTargets,
    AllTargetsRequest,
    AllUnexpandedTargets,
    CoarsenedTarget,
    CoarsenedTargets,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    Field,
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GeneratedTargets,
    GenerateSourcesRequest,
    GenerateTargetsRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    NoApplicableTargetsBehavior,
    RegisteredTargetTypes,
    SecondaryOwnerMixin,
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    SpecialCasedDependencies,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    Targets,
    TargetTypesToGenerateTargetsRequests,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
    UnrecognizedTargetTypeException,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership
from pants.option.global_options import FilesNotFoundBehavior, GlobalOptions, OwnersNotFoundBehavior
from pants.source.filespec import matches_filespec
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Address -> Target(s)
# -----------------------------------------------------------------------------------------------


@rule
async def resolve_unexpanded_targets(addresses: Addresses) -> UnexpandedTargets:
    wrapped_targets = await MultiGet(Get(WrappedTarget, Address, a) for a in addresses)
    return UnexpandedTargets(wrapped_target.target for wrapped_target in wrapped_targets)


@rule
def target_types_to_generate_targets_requests(
    union_membership: UnionMembership,
) -> TargetTypesToGenerateTargetsRequests:
    return TargetTypesToGenerateTargetsRequests(
        {
            request_cls.generate_from: request_cls  # type: ignore[misc]
            for request_cls in union_membership.get(GenerateTargetsRequest)
        }
    )


# We use a rule for this warning so that it gets memoized, i.e. doesn't get repeated for every
# offending target.
class _WarnDeprecatedTarget:
    pass


@dataclass(frozen=True)
class _WarnDeprecatedTargetRequest:
    tgt_type: type[Target]


@rule
def warn_deprecated_target_type(request: _WarnDeprecatedTargetRequest) -> _WarnDeprecatedTarget:
    tgt_type = request.tgt_type
    assert tgt_type.deprecated_alias_removal_version is not None
    warn_or_error(
        removal_version=tgt_type.deprecated_alias_removal_version,
        entity=f"the target name {tgt_type.deprecated_alias}",
        hint=(
            f"Instead, use `{tgt_type.alias}`, which behaves the same. Run `./pants "
            "update-build-files` to automatically fix your BUILD files."
        ),
    )
    return _WarnDeprecatedTarget()


# We use a rule for this warning so that it gets memoized, i.e. doesn't get repeated for every
# offending field.
class _WarnDeprecatedField:
    pass


@dataclass(frozen=True)
class _WarnDeprecatedFieldRequest:
    field_type: type[Field]


@rule
def warn_deprecated_field_type(request: _WarnDeprecatedFieldRequest) -> _WarnDeprecatedField:
    field_type = request.field_type
    assert field_type.deprecated_alias_removal_version is not None
    warn_or_error(
        removal_version=field_type.deprecated_alias_removal_version,
        entity=f"the field name {field_type.deprecated_alias}",
        hint=(
            f"Instead, use `{field_type.alias}`, which behaves the same. Run `./pants "
            "update-build-files` to automatically fix your BUILD files."
        ),
    )
    return _WarnDeprecatedField()


@rule
async def resolve_target(
    address: Address,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
) -> WrappedTarget:
    if not address.is_generated_target:
        target_adaptor = await Get(TargetAdaptor, Address, address)
        target_type = registered_target_types.aliases_to_types.get(target_adaptor.type_alias, None)
        if target_type is None:
            raise UnrecognizedTargetTypeException(
                target_adaptor.type_alias, registered_target_types, address
            )
        if (
            target_type.deprecated_alias is not None
            and target_type.deprecated_alias == target_adaptor.type_alias
            and not address.is_generated_target
        ):
            await Get(_WarnDeprecatedTarget, _WarnDeprecatedTargetRequest(target_type))
        target = target_type(target_adaptor.kwargs, address, union_membership)
        for field_type in target.field_types:
            if (
                field_type.deprecated_alias is not None
                and field_type.deprecated_alias in target_adaptor.kwargs
            ):
                await Get(_WarnDeprecatedField, _WarnDeprecatedFieldRequest(field_type))
        return WrappedTarget(target)

    wrapped_generator_tgt = await Get(
        WrappedTarget, Address, address.maybe_convert_to_target_generator()
    )
    generator_tgt = wrapped_generator_tgt.target
    if not target_types_to_generate_requests.is_generator(generator_tgt):
        # TODO: Error in this case. You should not use a generator address (or file address) if
        #  the generator does not actually generate.
        return wrapped_generator_tgt

    generate_request = target_types_to_generate_requests[type(generator_tgt)]
    generated = await Get(GeneratedTargets, GenerateTargetsRequest, generate_request(generator_tgt))
    if address not in generated:
        raise ValueError(
            f"The address `{address}` is not generated by the `{generator_tgt.alias}` target "
            f"`{generator_tgt.address}`, which only generates these addresses:\n\n"
            f"{bullet_list(addr.spec for addr in generated)}\n\n"
            "Did you mean to use one of those addresses?"
        )
    return WrappedTarget(generated[address])


@rule
async def resolve_targets(
    targets: UnexpandedTargets,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
) -> Targets:
    # Replace all generating targets with what it generates. Otherwise, keep it. If a target
    # generator does not generate any targets, keep the target generator.
    # TODO: This method does not preserve the order of inputs.
    expanded_targets: OrderedSet[Target] = OrderedSet()
    generator_targets = []
    generate_gets = []
    for tgt in targets:
        if (
            target_types_to_generate_requests.is_generator(tgt)
            and not tgt.address.is_generated_target
        ):
            generator_targets.append(tgt)
            generate_request = target_types_to_generate_requests[type(tgt)]
            generate_gets.append(
                Get(GeneratedTargets, GenerateTargetsRequest, generate_request(tgt))
            )
        else:
            expanded_targets.add(tgt)

    all_generated_targets = await MultiGet(generate_gets)
    expanded_targets.update(
        tgt
        for generator, generated_targets in zip(generator_targets, all_generated_targets)
        for tgt in (generated_targets.values() if generated_targets else {generator})
    )
    return Targets(expanded_targets)


@rule(desc="Find all targets in the project", level=LogLevel.DEBUG)
async def find_all_targets(_: AllTargetsRequest) -> AllTargets:
    tgts = await Get(Targets, AddressSpecs([MaybeEmptyDescendantAddresses("")]))
    return AllTargets(tgts)


@rule(desc="Find all targets in the project", level=LogLevel.DEBUG)
async def find_all_unexpanded_targets(_: AllTargetsRequest) -> AllUnexpandedTargets:
    tgts = await Get(UnexpandedTargets, AddressSpecs([MaybeEmptyDescendantAddresses("")]))
    return AllUnexpandedTargets(tgts)


@rule
async def find_all_targets_singleton() -> AllTargets:
    return await Get(AllTargets, AllTargetsRequest())


@rule
async def find_all_unexpanded_targets_singleton() -> AllUnexpandedTargets:
    return await Get(AllUnexpandedTargets, AllTargetsRequest())


# -----------------------------------------------------------------------------------------------
# TransitiveTargets
# -----------------------------------------------------------------------------------------------


class CycleException(Exception):
    def __init__(self, subject: Address, path: tuple[Address, ...]) -> None:
        path_string = "\n".join((f"-> {a}" if a == subject else f"   {a}") for a in path)
        super().__init__(
            f"The dependency graph contained a cycle:\n{path_string}\n\nTo fix this, first verify "
            "if your code has an actual import cycle. If it does, you likely need to re-architect "
            "your code to avoid the cycle.\n\nIf there is no cycle in your code, then you may need "
            "to use more granular targets. Split up the problematic targets into smaller targets "
            "with more granular `sources` fields so that you can adjust the `dependencies` fields "
            "to avoid introducing a cycle.\n\nAlternatively, use Python dependency inference "
            "(`--python-infer-imports`), rather than explicit `dependencies`. Pants will infer "
            "dependencies on specific files, rather than entire targets. This extra precision "
            "means that you will only have cycles if your code actually does have cycles in it."
        )
        self.subject = subject
        self.path = path


def _detect_cycles(
    roots: tuple[Address, ...], dependency_mapping: dict[Address, tuple[Address, ...]]
) -> None:
    path_stack: OrderedSet[Address] = OrderedSet()
    visited: set[Address] = set()

    def maybe_report_cycle(address: Address) -> None:
        # NB: File-level dependencies are cycle tolerant.
        if address.is_file_target or address not in path_stack:
            return

        # The path of the cycle is shorter than the entire path to the cycle: if the suffix of
        # the path representing the cycle contains a file dep, it is ignored.
        in_cycle = False
        for path_address in path_stack:
            if in_cycle and path_address.is_file_target:
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


@dataclass(frozen=True)
class _DependencyMappingRequest:
    tt_request: TransitiveTargetsRequest
    expanded_targets: bool


@dataclass(frozen=True)
class _DependencyMapping:
    mapping: FrozenDict[Address, tuple[Address, ...]]
    visited: FrozenOrderedSet[Target]
    roots_as_targets: Collection[Target]


@rule
async def transitive_dependency_mapping(request: _DependencyMappingRequest) -> _DependencyMapping:
    """This uses iteration, rather than recursion, so that we can tolerate dependency cycles.

    Unlike a traditional BFS algorithm, we batch each round of traversals via `MultiGet` for
    improved performance / concurrency.
    """
    roots_as_targets = await Get(UnexpandedTargets, Addresses(request.tt_request.roots))
    visited: OrderedSet[Target] = OrderedSet()
    queued = FrozenOrderedSet(roots_as_targets)
    dependency_mapping: dict[Address, tuple[Address, ...]] = {}
    while queued:
        direct_dependencies: tuple[Collection[Target], ...]
        if request.expanded_targets:
            direct_dependencies = await MultiGet(
                Get(
                    Targets,
                    DependenciesRequest(
                        tgt.get(Dependencies),
                        include_special_cased_deps=request.tt_request.include_special_cased_deps,
                    ),
                )
                for tgt in queued
            )
        else:
            direct_dependencies = await MultiGet(
                Get(
                    UnexpandedTargets,
                    DependenciesRequest(
                        tgt.get(Dependencies),
                        include_special_cased_deps=request.tt_request.include_special_cased_deps,
                    ),
                )
                for tgt in queued
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

    # NB: We use `roots_as_targets` to get the root addresses, rather than `request.roots`. This
    # is because expanding from the `Addresses` -> `Targets` may have resulted in generated
    # targets being used, so we need to use `roots_as_targets` to have this expansion.
    # TODO(#12871): Fix this to not be based on generated targets.
    _detect_cycles(tuple(t.address for t in roots_as_targets), dependency_mapping)
    return _DependencyMapping(
        FrozenDict(dependency_mapping), FrozenOrderedSet(visited), roots_as_targets
    )


@rule(desc="Resolve transitive targets")
async def transitive_targets(request: TransitiveTargetsRequest) -> TransitiveTargets:
    """Find all the targets transitively depended upon by the target roots."""

    dependency_mapping = await Get(_DependencyMapping, _DependencyMappingRequest(request, True))

    # Apply any transitive excludes (`!!` ignores).
    transitive_excludes: FrozenOrderedSet[Target] = FrozenOrderedSet()
    unevaluated_transitive_excludes = []
    for t in (*dependency_mapping.roots_as_targets, *dependency_mapping.visited):
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
        tuple(dependency_mapping.roots_as_targets),
        FrozenOrderedSet(dependency_mapping.visited.difference(transitive_excludes)),
    )


# -----------------------------------------------------------------------------------------------
# CoarsenedTargets
# -----------------------------------------------------------------------------------------------


@rule
async def coarsened_targets(addresses: Addresses) -> CoarsenedTargets:
    dependency_mapping = await Get(
        _DependencyMapping,
        _DependencyMappingRequest(
            # NB: We set include_special_cased_deps=True because although computing CoarsenedTargets
            # requires a transitive graph walk (to ensure that all cycles are actually detected),
            # the resulting CoarsenedTargets instance is not itself transitive: everything not directly
            # involved in a cycle with one of the input Addresses is discarded in the output.
            TransitiveTargetsRequest(addresses, include_special_cased_deps=True),
            expanded_targets=False,
        ),
    )
    addresses_to_targets = {
        t.address: t for t in [*dependency_mapping.visited, *dependency_mapping.roots_as_targets]
    }

    # Because this is Tarjan's SCC (TODO: update signature to guarantee), components are returned
    # in reverse topological order. We can thus assume when building the structure shared
    # `CoarsenedTarget` instances that each instance will already have had its dependencies
    # constructed.
    components = native_engine.strongly_connected_components(
        list(dependency_mapping.mapping.items())
    )

    coarsened_targets: dict[Address, CoarsenedTarget] = {}
    root_coarsened_targets = []
    root_addresses_set = set(addresses)
    for component in components:
        component = sorted(component)
        component_set = set(component)

        # For each member of the component, include the CoarsenedTarget for each of its external
        # dependencies.
        coarsened_target = CoarsenedTarget(
            (addresses_to_targets[a] for a in component),
            (
                coarsened_targets[d]
                for a in component
                for d in dependency_mapping.mapping[a]
                if d not in component_set
            ),
        )

        # Add to the coarsened_targets mapping under each of the component's Addresses.
        for address in component:
            coarsened_targets[address] = coarsened_target

        # If any of the input Addresses was a member of this component, it is a root.
        if component_set & root_addresses_set:
            root_coarsened_targets.append(coarsened_target)
    return CoarsenedTargets(tuple(root_coarsened_targets))


# -----------------------------------------------------------------------------------------------
# Find the owners of a file
# -----------------------------------------------------------------------------------------------


class InvalidOwnersOfArgs(Exception):
    pass


@dataclass(frozen=True)
class OwnersRequest:
    """A request for the owners of a set of file paths."""

    sources: tuple[str, ...]
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
    # For live files, we use Targets, which causes more precise, often file-level, targets
    # to be created. For deleted files we use UnexpandedTargets, which have the original declared
    # glob.
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
                matches_filespec(candidate_tgt.get(SourcesField).filespec, paths=sources_set)
            )
            # Also consider secondary ownership, meaning it's not a `SourcesField` field with
            # primary ownership, but the target still should match the file. We can't use
            # `tgt.get()` because this is a mixin, and there technically may be >1 field.
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


@rule
def extract_owners_not_found_behavior(global_options: GlobalOptions) -> OwnersNotFoundBehavior:
    return cast(OwnersNotFoundBehavior, global_options.options.owners_not_found_behavior)


def _log_or_raise_unmatched_owners(
    file_paths: Sequence[PurePath],
    owners_not_found_behavior: OwnersNotFoundBehavior,
    ignore_option: str | None = None,
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
    filesystem_specs: FilesystemSpecs, owners_not_found_behavior: OwnersNotFoundBehavior
) -> Addresses:
    """Find the owner(s) for each FilesystemSpec."""
    paths_per_include = await MultiGet(
        Get(
            Paths,
            PathGlobs,
            filesystem_specs.path_globs_for_spec(
                spec, owners_not_found_behavior.to_glob_match_error_behavior()
            ),
        )
        for spec in filesystem_specs.file_includes
    )
    owners_per_include = await MultiGet(
        Get(Owners, OwnersRequest(sources=paths.files)) for paths in paths_per_include
    )
    addresses: set[Address] = set()
    for spec, owners in zip(filesystem_specs.file_includes, owners_per_include):
        if (
            owners_not_found_behavior != OwnersNotFoundBehavior.ignore
            and isinstance(spec, FileLiteralSpec)
            and not owners
        ):
            _log_or_raise_unmatched_owners(
                [PurePath(str(spec))],
                owners_not_found_behavior,
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
async def resolve_specs_snapshot(
    specs: Specs, owners_not_found_behavior: OwnersNotFoundBehavior
) -> SpecsSnapshot:
    """Resolve all files matching the given specs.

    Address specs will use their `SourcesField` field, and Filesystem specs will use whatever args
    were given. Filesystem specs may safely refer to files with no owning target.
    """
    targets = await Get(Targets, AddressSpecs, specs.address_specs)
    all_hydrated_sources = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt[SourcesField]))
        for tgt in targets
        if tgt.has_field(SourcesField)
    )

    filesystem_specs_digest = (
        await Get(
            Digest,
            PathGlobs,
            specs.filesystem_specs.to_path_globs(
                owners_not_found_behavior.to_glob_match_error_behavior()
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
# Resolve SourcesField
# -----------------------------------------------------------------------------------------------


@rule
def extract_files_not_found_behavior(global_options: GlobalOptions) -> FilesNotFoundBehavior:
    return cast(FilesNotFoundBehavior, global_options.options.files_not_found_behavior)


class AmbiguousCodegenImplementationsException(Exception):
    """Exception for when there are multiple codegen implementations and it is ambiguous which to
    use."""

    def __init__(
        self,
        generators: Iterable[type[GenerateSourcesRequest]],
        *,
        for_sources_types: Iterable[type[SourcesField]],
    ) -> None:
        all_same_generator_paths = (
            len({(generator.input, generator.output) for generator in generators}) == 1
        )
        example_generator = list(generators)[0]
        input = example_generator.input.__name__
        if all_same_generator_paths:
            output = example_generator.output.__name__
            super().__init__(
                f"Multiple of the registered code generators can generate {output} from {input}. "
                "It is ambiguous which implementation to use.\n\nPossible implementations:\n\n"
                f"{bullet_list(sorted(generator.__name__ for generator in generators))}"
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
                f"output type:\n\n"
                f"{bullet_list(possible_generators_with_output)}"
            )


@rule(desc="Hydrate the `sources` field")
async def hydrate_sources(
    request: HydrateSourcesRequest,
    files_not_found_behavior: FilesNotFoundBehavior,
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
    def compatible_with_sources_field(valid_type: type[SourcesField]) -> bool:
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
    path_globs = sources_field.path_globs(files_not_found_behavior)
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
    request: SourcesPathsRequest, files_not_found_behavior: FilesNotFoundBehavior
) -> SourcesPaths:
    sources_field = request.field
    path_globs = sources_field.path_globs(files_not_found_behavior)
    paths = await Get(Paths, PathGlobs, path_globs)
    sources_field.validate_resolved_files(paths.files)
    return SourcesPaths(files=paths.files, dirs=paths.dirs)


# -----------------------------------------------------------------------------------------------
# Resolve addresses, including the Dependencies field
# -----------------------------------------------------------------------------------------------


class SubprojectRoots(Collection[str]):
    pass


@rule
def extract_subproject_roots(global_options: GlobalOptions) -> SubprojectRoots:
    return SubprojectRoots(global_options.options.subproject_roots)


class ParsedDependencies(NamedTuple):
    addresses: list[AddressInput]
    ignored_addresses: list[AddressInput]


class TransitiveExcludesNotSupportedError(ValueError):
    def __init__(
        self,
        *,
        bad_value: str,
        address: Address,
        registered_target_types: Iterable[type[Target]],
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
    subproject_roots: SubprojectRoots,
) -> ExplicitlyProvidedDependencies:
    parse = functools.partial(
        AddressInput.parse,
        relative_to=request.field.address.spec_path,
        subproject_roots=subproject_roots,
    )

    addresses: list[AddressInput] = []
    ignored_addresses: list[AddressInput] = []
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
    request: DependenciesRequest,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    union_membership: UnionMembership,
    subproject_roots: SubprojectRoots,
) -> Addresses:
    wrapped_tgt, explicitly_provided = await MultiGet(
        Get(WrappedTarget, Address, request.field.address),
        Get(ExplicitlyProvidedDependencies, DependenciesRequest, request),
    )
    tgt = wrapped_tgt.target

    # Inject any dependencies (based on `Dependencies` field rather than `SourcesField`).
    inject_request_types = union_membership.get(InjectDependenciesRequest)
    injected = await MultiGet(
        Get(InjectedDependencies, InjectDependenciesRequest, inject_request_type(request.field))
        for inject_request_type in inject_request_types
        if isinstance(request.field, inject_request_type.inject_for)
    )

    # Infer any dependencies (based on `SourcesField` field).
    inference_request_types = union_membership.get(InferDependenciesRequest)
    inferred: tuple[InferredDependencies, ...] = ()
    if inference_request_types:
        sources_field = tgt.get(SourcesField)
        relevant_inference_request_types = [
            inference_request_type
            for inference_request_type in inference_request_types
            # NB: `type: ignore`d due to https://github.com/python/mypy/issues/9815.
            if isinstance(sources_field, inference_request_type.infer_from)  # type: ignore[misc]
        ]
        inferred = await MultiGet(
            Get(
                InferredDependencies,
                InferDependenciesRequest,
                inference_request_type(sources_field),
            )
            for inference_request_type in relevant_inference_request_types
        )

    # If it's a target generator, inject dependencies on all of its generated targets.
    generated_addresses: tuple[Address, ...] = ()
    if target_types_to_generate_requests.is_generator(tgt) and not tgt.address.is_generated_target:
        generate_request = target_types_to_generate_requests[type(tgt)]
        generated_targets = await Get(
            GeneratedTargets, GenerateTargetsRequest, generate_request(tgt)
        )
        generated_addresses = tuple(generated_targets.keys())

    # If the target has `SpecialCasedDependencies`, such as the `archive` target having
    # `files` and `packages` fields, then we possibly include those too. We don't want to always
    # include those dependencies because they should often be excluded from the result due to
    # being handled elsewhere in the calling code.
    special_cased: tuple[Address, ...] = ()
    if request.include_special_cased_deps:
        # Unlike normal, we don't use `tgt.get()` because there may be >1 subclass of
        # SpecialCasedDependencies.
        special_cased_fields = tuple(
            field
            for field in tgt.field_values.values()
            if isinstance(field, SpecialCasedDependencies)
        )
        # We can't use the normal `Get(Addresses, UnparsedAddressInputs)` due to a graph cycle.
        special_cased = await MultiGet(
            Get(
                Address,
                AddressInput,
                AddressInput.parse(
                    addr,
                    relative_to=tgt.address.spec_path,
                    subproject_roots=subproject_roots,
                ),
            )
            for special_cased_field in special_cased_fields
            for addr in special_cased_field.to_unparsed_address_inputs().values
        )

    result = {
        addr
        for addr in (
            *generated_addresses,
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
    request: UnparsedAddressInputs, subproject_roots: SubprojectRoots
) -> Addresses:
    addresses = await MultiGet(
        Get(
            Address,
            AddressInput,
            AddressInput.parse(
                v, relative_to=request.relative_to, subproject_roots=subproject_roots
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
        applicable_target_types: Iterable[type[Target]],
        goal_description: str,
    ) -> None:
        applicable_target_aliases = sorted(
            {target_type.alias for target_type in applicable_target_types}
        )
        inapplicable_target_aliases = sorted({tgt.alias for tgt in targets})
        msg = (
            "No applicable files or targets matched."
            if inapplicable_target_aliases
            else "No files or targets specified."
        )
        msg += (
            f" {goal_description.capitalize()} works "
            f"with these target types:\n\n"
            f"{bullet_list(applicable_target_aliases)}\n\n"
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
                f"However, you only specified{specs_description}these target types:\n\n"
                f"{bullet_list(inapplicable_target_aliases)}\n\n"
            )

        # Add a remedy.
        #
        # We sometimes suggest using `./pants filedeps` to find applicable files. However, this
        # command only works if at least one of the targets has a SourcesField field.
        #
        # NB: Even with the "secondary owners" mechanism - used by target types like `pex_binary`
        # and `python_awslambda` to still work with file args - those targets will not show the
        # associated files when using filedeps.
        filedeps_goal_works = any(
            tgt.class_has_field(SourcesField, union_membership) for tgt in applicable_target_types
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
        addresses = sorted(tgt.address.spec for tgt in targets)
        super().__init__(
            f"{goal_description.capitalize()} only works with one valid target, but was given "
            f"multiple valid targets:\n\n{bullet_list(addresses)}\n\n"
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
        super().__init__(
            f"Multiple of the registered implementations for {goal_description} work for "
            f"{target.address} (target type {repr(target.alias)}). It is ambiguous which "
            "implementation to use.\n\nPossible implementations:\n\n"
            f"{bullet_list(possible_field_sets_types)}"
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
