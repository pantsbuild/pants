# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import itertools
import logging
import os.path
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import DefaultDict, Dict, Iterable, List, NamedTuple, Sequence, Set, Tuple, Type, Union

from pants.base.exceptions import ResolveError
from pants.base.specs import (
    AddressSpecs,
    AscendantAddresses,
    FilesystemLiteralSpec,
    FilesystemMergedSpec,
    FilesystemResolvedGlobSpec,
    FilesystemSpecs,
    Specs,
)
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressesWithOrigins,
    AddressWithOrigin,
    BuildFileAddress,
)
from pants.engine.collection import Collection
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
    Snapshot,
    SourcesSnapshot,
)
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
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
    Target,
    Targets,
    TargetsToValidFieldSets,
    TargetsToValidFieldSetsRequest,
    TargetsWithOrigins,
    TargetWithOrigin,
    TransitiveTargets,
    UnrecognizedTargetTypeException,
    WrappedTarget,
    _AbstractFieldSet,
    generate_subtarget,
)
from pants.engine.unions import UnionMembership
from pants.option.global_options import GlobalOptions, OwnersNotFoundBehavior
from pants.source.filespec import matches_filespec
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Address -> Target(s)
# -----------------------------------------------------------------------------------------------


@rule
async def resolve_target(
    address: Address, registered_target_types: RegisteredTargetTypes
) -> WrappedTarget:
    if address.generated_base_target_name:
        base_target = await Get(WrappedTarget, Address, address.maybe_convert_to_base_target())
        subtarget = generate_subtarget(
            base_target.target,
            full_file_name=PurePath(address.spec_path, address.target_name).as_posix(),
        )
        return WrappedTarget(subtarget)

    target_adaptor = await Get(TargetAdaptor, Address, address)
    target_type = registered_target_types.aliases_to_types.get(target_adaptor.type_alias, None)
    if target_type is None:
        raise UnrecognizedTargetTypeException(
            target_adaptor.type_alias, registered_target_types, address=address
        )
    target = target_type(target_adaptor.kwargs, address=address)
    return WrappedTarget(target)


@rule
async def resolve_targets(addresses: Addresses) -> Targets:
    wrapped_targets = await MultiGet(Get(WrappedTarget, Address, a) for a in addresses)
    return Targets(wrapped_target.target for wrapped_target in wrapped_targets)


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
    targets_with_origins = await MultiGet(
        Get(TargetWithOrigin, AddressWithOrigin, address_with_origin)
        for address_with_origin in addresses_with_origins
    )
    return TargetsWithOrigins(targets_with_origins)


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

    def visit(address: Address):
        if address in visited:
            # NB: File-level dependencies are cycle tolerant.
            if not address.generated_base_target_name and address in path_stack:
                raise CycleException(address, (*path_stack, address))
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

    transitive_targets = TransitiveTargets(tuple(targets), FrozenOrderedSet(visited))
    _detect_cycles(tuple(t.address for t in targets), dependency_mapping)
    return transitive_targets


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
    sources_set = FrozenOrderedSet(owners_request.sources)
    dirs_set = FrozenOrderedSet(os.path.dirname(source) for source in sources_set)

    # Walk up the buildroot looking for targets that would conceivably claim changed sources.
    candidate_specs = tuple(AscendantAddresses(directory=d) for d in dirs_set)
    candidate_targets = await Get(Targets, AddressSpecs(candidate_specs))
    candidate_target_sources = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt.get(Sources))) for tgt in candidate_targets
    )
    build_file_addresses = await MultiGet(
        Get(BuildFileAddress, Address, tgt.address) for tgt in candidate_targets
    )

    # We use this to determine if any of the matched files are deleted or not.
    all_source_files = set(
        itertools.chain.from_iterable(
            sources.snapshot.files for sources in candidate_target_sources
        )
    )

    file_name_to_generated_address: Dict[str, Address] = {}
    file_names_with_multiple_owners: OrderedSet[str] = OrderedSet()
    original_addresses_due_to_deleted_files: OrderedSet[Address] = OrderedSet()
    original_addresses_due_to_multiple_owners: OrderedSet[Address] = OrderedSet()
    unmatched_sources = set(sources_set)
    for candidate_tgt, candidate_tgt_sources, bfa in zip(
        candidate_targets, candidate_target_sources, build_file_addresses
    ):
        matching_files = set(
            matches_filespec(candidate_tgt.get(Sources).filespec, paths=sources_set)
        )
        if bfa.rel_path not in sources_set and not matching_files:
            continue
        unmatched_sources -= matching_files
        deleted_files_matched = bool(matching_files - all_source_files)
        if deleted_files_matched:
            original_addresses_due_to_deleted_files.add(candidate_tgt.address)
            continue
        # Else, we generate subtargets for greater precision. We use those subtargets, unless
        # there are multiple owners of their file.
        generated_subtargets = tuple(
            generate_subtarget(candidate_tgt, full_file_name=f)
            for f in candidate_tgt_sources.snapshot.files
        )
        for generated_subtarget, file_name in zip(
            generated_subtargets, candidate_tgt_sources.snapshot.files
        ):
            if bfa.rel_path not in sources_set and not matches_filespec(
                generated_subtarget.get(Sources).filespec, paths=sources_set
            ):
                continue

            if file_name in file_name_to_generated_address:
                file_names_with_multiple_owners.add(file_name)
                original_addresses_due_to_multiple_owners.add(candidate_tgt.address)
                # We also add the original target of the generated address already stored.
                already_stored_generated_address = file_name_to_generated_address[file_name]
                original_addresses_due_to_multiple_owners.add(
                    already_stored_generated_address.maybe_convert_to_base_target()
                )
            else:
                file_name_to_generated_address[file_name] = generated_subtarget.address

    def already_covered_by_original_addresses(file_name: str, generated_address: Address) -> bool:
        multiple_generated_subtarget_owners = file_name in file_names_with_multiple_owners
        original_address = generated_address.maybe_convert_to_base_target()
        return (
            multiple_generated_subtarget_owners
            or original_address in original_addresses_due_to_deleted_files
            or original_address in original_addresses_due_to_multiple_owners
        )

    if (
        unmatched_sources
        and owners_request.owners_not_found_behavior != OwnersNotFoundBehavior.ignore
    ):
        _log_or_raise_unmatched_owners(
            [PurePath(path) for path in unmatched_sources], owners_request.owners_not_found_behavior
        )

    remaining_generated_addresses = FrozenOrderedSet(
        address
        for file_name, address in file_name_to_generated_address.items()
        if not already_covered_by_original_addresses(file_name, address)
    )
    return Owners(
        [
            *original_addresses_due_to_deleted_files,
            *original_addresses_due_to_multiple_owners,
            *remaining_generated_addresses,
        ]
    )


# -----------------------------------------------------------------------------------------------
# Specs -> Addresses
# -----------------------------------------------------------------------------------------------


def _log_or_raise_unmatched_owners(
    file_paths: Sequence[PurePath], owners_not_found_behavior: OwnersNotFoundBehavior
) -> None:
    msgs = []
    for file_path in file_paths:
        msgs.append(
            f"No owning targets could be found for the file `{file_path}`.\n\nPlease check "
            f"that there is a BUILD file in `{file_path.parent}` with a target whose `sources` "
            f"field includes `{file_path}`. See https://www.pantsbuild.org/docs/targets for more "
            "information on target definitions.\nIf you would like to ignore un-owned files, "
            "please pass `--owners-not-found-behavior=ignore`."
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

    When a file has only one owning target, we generate a subtarget from that owner whose source's
    field only refers to that one file. Otherwise, we use all the original owning targets.

    This will merge FilesystemSpecs that come from the same owning target into a single
    FilesystemMergedSpec.
    """
    pathglobs_per_include = (
        filesystem_specs.path_globs_for_spec(
            spec, global_options.options.owners_not_found_behavior.to_glob_match_error_behavior(),
        )
        for spec in filesystem_specs.includes
    )
    snapshot_per_include = await MultiGet(
        Get(Snapshot, PathGlobs, pg) for pg in pathglobs_per_include
    )
    owners_per_include = await MultiGet(
        Get(Owners, OwnersRequest(sources=snapshot.files)) for snapshot in snapshot_per_include
    )
    addresses_to_specs: DefaultDict[
        Address, List[Union[FilesystemLiteralSpec, FilesystemResolvedGlobSpec]]
    ] = defaultdict(list)
    for spec, snapshot, owners in zip(
        filesystem_specs.includes, snapshot_per_include, owners_per_include
    ):
        if (
            global_options.options.owners_not_found_behavior != OwnersNotFoundBehavior.ignore
            and isinstance(spec, FilesystemLiteralSpec)
            and not owners
        ):
            _log_or_raise_unmatched_owners(
                [PurePath(spec.to_spec_string())], global_options.options.owners_not_found_behavior
            )
        # We preserve what literal files any globs resolved to. This allows downstream goals to be
        # more precise in which files they operate on.
        origin: Union[FilesystemLiteralSpec, FilesystemResolvedGlobSpec] = (
            spec
            if isinstance(spec, FilesystemLiteralSpec)
            else FilesystemResolvedGlobSpec(glob=spec.glob, files=snapshot.files)
        )
        for address in owners:
            addresses_to_specs[address].append(origin)
    return AddressesWithOrigins(
        AddressWithOrigin(
            address, specs[0] if len(specs) == 1 else FilesystemMergedSpec.create(specs)
        )
        for address, specs in addresses_to_specs.items()
    )


@rule
async def resolve_addresses_with_origins(specs: Specs) -> AddressesWithOrigins:
    from_address_specs, from_filesystem_specs = await MultiGet(
        Get(AddressesWithOrigins, AddressSpecs, specs.address_specs),
        Get(AddressesWithOrigins, FilesystemSpecs, specs.filesystem_specs),
    )
    # It's possible to resolve the same address both with filesystem specs and address specs. We
    # dedupe, but must go through some ceremony for the equality check because the OriginSpec will
    # differ. We must also consider that the filesystem spec may have resulted in a generated
    # subtarget; if the user explicitly specified the original owning target, we should use the
    # original target rather than its generated subtarget.
    address_spec_addresses = FrozenOrderedSet(awo.address for awo in from_address_specs)
    return AddressesWithOrigins(
        [
            *from_address_specs,
            *(
                awo
                for awo in from_filesystem_specs
                if awo.address.maybe_convert_to_base_target() not in address_spec_addresses
            ),
        ]
    )


# -----------------------------------------------------------------------------------------------
# SourcesSnapshot
# -----------------------------------------------------------------------------------------------


@rule
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

    filesystem_specs_snapshot = (
        await Get(
            Snapshot,
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
    if filesystem_specs_snapshot:
        digests.append(filesystem_specs_snapshot.digest)
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
    glob_match_error_behavior: GlobMatchErrorBehavior,
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
    globs = sources_field.sanitized_raw_value
    if globs is None:
        return HydratedSources(EMPTY_SNAPSHOT, sources_field.filespec, sources_type=sources_type)

    conjunction = (
        GlobExpansionConjunction.all_match
        if not sources_field.default or (set(globs) != set(sources_field.default))
        else GlobExpansionConjunction.any_match
    )
    snapshot = await Get(
        Snapshot,
        PathGlobs(
            (sources_field.prefix_glob_with_address(glob) for glob in globs),
            conjunction=conjunction,
            glob_match_error_behavior=glob_match_error_behavior,
            # TODO(#9012): add line number referring to the sources field. When doing this, we'll
            # likely need to `await Get(BuildFileAddress](Address)`.
            description_of_origin=(
                f"{sources_field.address}'s `{sources_field.alias}` field"
                if glob_match_error_behavior != GlobMatchErrorBehavior.ignore
                else None
            ),
        ),
    )
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


class InvalidFileDependencyException(Exception):
    pass


class UnusedDependencyIgnoresException(Exception):
    def __init__(
        self, address: Address, *, unused_ignores: Iterable[Address], result: Iterable[Address]
    ) -> None:
        # If the address was generated, we convert back to the original base target to correspond to
        # what users actually put in BUILD files.
        address = address.maybe_convert_to_base_target()
        sorted_unused_ignores = sorted([f"!{addr}" for addr in unused_ignores])
        formatted_unused_ignores = (
            repr(sorted_unused_ignores[0])
            if len(sorted_unused_ignores) == 1
            else str(sorted_unused_ignores)
        )
        bulleted_list_sep = "\n  * "
        possible_deps = sorted(addr.spec for addr in result)
        super().__init__(
            f"The target {address} includes {formatted_unused_ignores} in its `dependencies` field, "
            f"but {'it does' if len(sorted_unused_ignores) == 1 else 'they do'} not match any of "
            f"the resolved dependencies. Instead, please choose from the dependencies that are "
            f"being used:\n\n{bulleted_list_sep}{bulleted_list_sep.join(possible_deps)}"
        )


class ParsedDependencies(NamedTuple):
    addresses: List[Address]
    files: List[str]
    ignored_addresses: List[Address]
    ignored_files: List[str]


def parse_dependencies_field(
    raw_value: Iterable[str], *, spec_path: str, subproject_roots: Sequence[str]
) -> ParsedDependencies:
    parse_as_address = functools.partial(
        Address.parse, relative_to=spec_path, subproject_roots=subproject_roots
    )

    def parse(value: str) -> Union[Address, str]:
        # We allow `//` to specify the value is relative to the build root. This is only actually
        # necessary for top-level addresses, though, like `//:tgt`. Otherwise, we can strip `//`.
        if value.startswith("//") and not value.startswith("//:"):
            value = value[2:]
        if ":" in value:
            return parse_as_address(value)
        if value.startswith("./"):
            return PurePath(spec_path, value).as_posix()
        if PurePath(value).suffix:
            return value
        return parse_as_address(value)

    addresses: List[Address] = []
    files: List[str] = []
    ignored_addresses: List[Address] = []
    ignored_files: List[str] = []
    for v in raw_value:
        is_ignore = v.startswith("!")
        if is_ignore:
            v = v[1:]
        result = parse(v)
        if is_ignore:
            collection = ignored_addresses if isinstance(result, Address) else ignored_files
        else:
            collection = addresses if isinstance(result, Address) else files
        collection.append(result)  # type: ignore[attr-defined]
    return ParsedDependencies(addresses, files, ignored_addresses, ignored_files)


def validate_explicit_file_dep(
    address: Address, full_file: str, owners: Sequence[Address], *, is_an_ignore: bool = False
) -> None:
    if is_an_ignore:
        full_file = f"!{full_file}"
    # If the address was generated, we convert back to the original base target to correspond to
    # what users actually put in BUILD files.
    address = address.maybe_convert_to_base_target()
    if len(owners) > 1:
        original_addresses = sorted(owner.maybe_convert_to_base_target().spec for owner in owners)
        if is_an_ignore:
            original_addresses = [f"!{addr}" for addr in original_addresses]
        raise InvalidFileDependencyException(
            f"The target {address} includes {repr(full_file)} in its `dependencies` "
            "field, but there are multiple owners of that file so it is ambiguous which one "
            "Pants should use. Please instead change the `sources` fields of the owning "
            "targets so that only one target owns this file, or choose which owner you want "
            f"to use: {original_addresses}"
        )
    # If a file does not exist, but it matches the `sources` glob of a target, then it will
    # have an owning target.
    file_does_not_exist = len(owners) == 1 and not owners[0].generated_base_target_name
    if not owners or file_does_not_exist:
        raise InvalidFileDependencyException(
            f"The target {address} includes {repr(full_file)} in its `dependencies` "
            "field, but there are no owners of that file. Please check that the file exists, "
            "that you spelled the file correctly, and that there is a target that includes the "
            "file in its `sources` field."
        )


@rule
async def resolve_dependencies(
    request: DependenciesRequest, union_membership: UnionMembership, global_options: GlobalOptions
) -> Addresses:
    provided = parse_dependencies_field(
        request.field.sanitized_raw_value or (),
        spec_path=request.field.address.spec_path,
        subproject_roots=global_options.options.subproject_roots,
    )

    explicit_file_deps_owners = await MultiGet(
        Get(Owners, OwnersRequest((f,))) for f in provided.files
    )
    for f, owners in zip(provided.files, explicit_file_deps_owners):
        validate_explicit_file_dep(request.field.address, f, owners)

    explicit_file_deps_ignore_owners = await MultiGet(
        Get(Owners, OwnersRequest((f,))) for f in provided.ignored_files
    )
    for f, owners in zip(provided.ignored_files, explicit_file_deps_ignore_owners):
        validate_explicit_file_dep(request.field.address, f, owners, is_an_ignore=True)

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
    inferred = [InferredDependencies()]
    if global_options.options.dependency_inference and inference_request_types:
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

    flattened_ignore_file_deps_owners = set(
        itertools.chain.from_iterable(explicit_file_deps_ignore_owners)
    )

    original_addresses: Set[Address] = set()
    all_generated_addresses: Set[Address] = set()
    used_ignored_addresses: Set[Address] = set()
    used_ignored_file_deps: Set[Address] = set()
    for addr in (
        *provided.addresses,
        *itertools.chain.from_iterable(explicit_file_deps_owners),
        *itertools.chain.from_iterable(injected),
        *itertools.chain.from_iterable(inferred),
    ):
        if addr.generated_base_target_name:
            collection = (
                used_ignored_file_deps
                if addr in flattened_ignore_file_deps_owners
                else all_generated_addresses
            )
        else:
            collection = (
                used_ignored_addresses if addr in provided.ignored_addresses else original_addresses
            )
        collection.add(addr)

    # We check if a generated subtarget's original base target is already included or if ts base
    # target is the target that we're resolving dependencies for. In either of these cases, it
    # would be redundant to include the generated subtarget.
    remaining_generated_addresses = set()
    for generated_addr in all_generated_addresses:
        base_addr = generated_addr.maybe_convert_to_base_target()
        if base_addr in original_addresses or base_addr == request.field.address:
            continue
        remaining_generated_addresses.add(generated_addr)

    result = sorted({*original_addresses, *remaining_generated_addresses})

    unused_ignores = {*provided.ignored_addresses, *flattened_ignore_file_deps_owners} - {
        *used_ignored_addresses,
        *used_ignored_file_deps,
    }
    # If there are unused ignores and this is not a generated subtarget, we eagerly error so that
    # the user isn't falsely led to believe the ignore is working. We do not do this for generated
    # subtargets because we cannot guarantee that the ignore specified in the original owning
    # target would be used for all generated subtargets.
    if unused_ignores and not request.field.address.generated_base_target_name:
        raise UnusedDependencyIgnoresException(
            request.field.address, unused_ignores=unused_ignores, result=result
        )

    return Addresses(result)


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
            {
                target_with_origin.origin.to_spec_string()
                for target_with_origin in targets_with_origins
            }
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
            targets_with_origins,
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
        # Address -> Target
        resolve_target,
        resolve_targets,
        # AddressWithOrigin -> TargetWithOrigin
        resolve_target_with_origin,
        resolve_targets_with_origins,
        # TransitiveTargets
        transitive_targets,
        # Owners
        find_owners,
        RootRule(OwnersRequest),
        # Specs -> AddressesWithOrigins
        addresses_with_origins_from_filesystem_specs,
        resolve_addresses_with_origins,
        RootRule(Specs),
        # SourcesSnapshot
        resolve_sources_snapshot,
        # Sources field
        hydrate_sources,
        RootRule(HydrateSourcesRequest),
        # Dependencies field
        resolve_dependencies,
        RootRule(DependenciesRequest),
        RootRule(InjectDependenciesRequest),
        RootRule(InferDependenciesRequest),
        # FieldSets
        find_valid_field_sets,
        RootRule(TargetsToValidFieldSetsRequest),
    ]
