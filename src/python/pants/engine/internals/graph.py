# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
import os.path
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import PurePath
from typing import DefaultDict, Dict, List, Tuple, Union

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
from pants.engine.fs import MergeDigests, PathGlobs, Snapshot, SourcesSnapshot
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    RegisteredTargetTypes,
    Sources,
    Target,
    Targets,
    TargetsWithOrigins,
    TargetWithOrigin,
    TransitiveTarget,
    TransitiveTargets,
    UnrecognizedTargetTypeException,
    WrappedTarget,
    generate_subtarget,
)
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


@rule
async def transitive_target(wrapped_root: WrappedTarget) -> TransitiveTarget:
    root = wrapped_root.target
    if not root.has_field(Dependencies):
        return TransitiveTarget(root, ())
    dependency_addresses = await Get(Addresses, DependenciesRequest(root[Dependencies]))
    dependencies = await MultiGet(Get(TransitiveTarget, Address, d) for d in dependency_addresses)
    return TransitiveTarget(root, dependencies)


@rule
async def transitive_targets(addresses: Addresses) -> TransitiveTargets:
    """Given Addresses, kicks off recursion on expansion of TransitiveTargets.

    The TransitiveTarget dataclass represents a structure-shared graph, which we walk and flatten
    here. The engine memoizes the computation of TransitiveTarget, so when multiple
    TransitiveTargets objects are being constructed for multiple roots, their structure will be
    shared.
    """
    tts = await MultiGet(Get(TransitiveTarget, Address, a) for a in addresses)

    dependencies: OrderedSet[Target] = OrderedSet()
    to_visit = deque(itertools.chain.from_iterable(tt.dependencies for tt in tts))
    while to_visit:
        tt = to_visit.popleft()
        if tt.root in dependencies:
            continue
        dependencies.add(tt.root)
        to_visit.extend(tt.dependencies)

    return TransitiveTargets(tuple(tt.root for tt in tts), FrozenOrderedSet(dependencies))


# -----------------------------------------------------------------------------------------------
# Find the owners of a file
# -----------------------------------------------------------------------------------------------


class InvalidOwnersOfArgs(Exception):
    pass


@dataclass(frozen=True)
class OwnersRequest:
    """A request for the owners of a set of file paths."""

    sources: Tuple[str, ...]


class Owners(Collection[Address]):
    pass


@rule
async def find_owners(owners_request: OwnersRequest) -> Owners:
    sources_set = FrozenOrderedSet(owners_request.sources)
    dirs_set = FrozenOrderedSet(os.path.dirname(source) for source in sources_set)

    # Walk up the buildroot looking for targets that would conceivably claim changed sources.
    candidate_specs = tuple(AscendantAddresses(directory=d) for d in dirs_set)
    candidate_explicit_targets = await Get(Targets, AddressSpecs(candidate_specs))

    # Generate subtargets. This gives us file-level precision, where each target only owns one file.
    # We may not end up using every generated subtarget, but we need to consider each of them. We
    # also consider the original owning targets so that we can handle deleted files that would have
    # belonged to those targets.
    candidate_explicit_target_sources = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt.get(Sources)))
        for tgt in candidate_explicit_targets
    )
    candidate_targets: OrderedSet[Target] = OrderedSet(candidate_explicit_targets)
    for explicit_tgt, explicit_tgt_sources in zip(
        candidate_explicit_targets, candidate_explicit_target_sources
    ):
        candidate_targets.update(
            generate_subtarget(explicit_tgt, full_file_name=f)
            for f in explicit_tgt_sources.snapshot.files
        )

    build_file_addresses = await MultiGet(
        Get(BuildFileAddress, Address, tgt.address) for tgt in candidate_targets
    )

    # Determine which candidates are owners. We try to use generated subtargets, but fall back to
    # the original owning target if a) there are multiple owners of the same file or b) a matched
    # file is deleted; deleted files cannot have a generated subtarget because that file no longer
    # exists.
    all_source_files = set(
        itertools.chain.from_iterable(
            sources.snapshot.files for sources in candidate_explicit_target_sources
        )
    )
    file_name_to_generated_address: Dict[str, Address] = {}
    file_names_with_multiple_owners: OrderedSet[str] = OrderedSet()
    original_addresses_due_to_deleted_files: OrderedSet[Address] = OrderedSet()
    original_addresses_due_to_multiple_owners: OrderedSet[Address] = OrderedSet()
    for candidate_tgt, bfa in zip(candidate_targets, build_file_addresses):
        matching_files = matches_filespec(candidate_tgt.get(Sources).filespec, paths=sources_set)
        if bfa.rel_path not in sources_set and not matching_files:
            continue
        if candidate_tgt.address.generated_base_target_name is None:
            deleted_files_matched = bool(set(matching_files) - all_source_files)
            if deleted_files_matched:
                original_addresses_due_to_deleted_files.add(candidate_tgt.address)
            continue
        # Else, we know it's a generated subtarget. We check if there are multiple owners of its
        # file.
        file_name = PurePath(
            candidate_tgt.address.spec_path, candidate_tgt.address.target_name
        ).as_posix()
        if file_name in file_name_to_generated_address:
            file_names_with_multiple_owners.add(file_name)
            original_addresses_due_to_multiple_owners.add(
                candidate_tgt.address.maybe_convert_to_base_target()
            )
            # We also add the original target of the generated address already stored.
            already_stored_generated_address = file_name_to_generated_address[file_name]
            original_addresses_due_to_multiple_owners.add(
                already_stored_generated_address.maybe_convert_to_base_target()
            )
        else:
            file_name_to_generated_address[file_name] = candidate_tgt.address

    def already_covered_by_original_addresses(file_name: str, generated_address: Address) -> bool:
        multiple_generated_subtarget_owners = file_name in file_names_with_multiple_owners
        original_address = generated_address.maybe_convert_to_base_target()
        return (
            multiple_generated_subtarget_owners
            or original_address in original_addresses_due_to_deleted_files
            or original_address in original_addresses_due_to_multiple_owners
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
# FilesystemSpecs -> Addresses
# -----------------------------------------------------------------------------------------------


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
            file_path = PurePath(spec.to_spec_string())
            msg = (
                f"No owning targets could be found for the file `{file_path}`.\n\nPlease check "
                f"that there is a BUILD file in `{file_path.parent}` with a target whose `sources` "
                f"field includes `{file_path}`. See https://pants.readme.io/docs/targets for more "
                "information on target definitions.\nIf you would like to ignore un-owned files, "
                "please pass `--owners-not-found-behavior=ignore`."
            )
            if global_options.options.owners_not_found_behavior == OwnersNotFoundBehavior.warn:
                logger.warning(msg)
            else:
                raise ResolveError(msg)
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


def rules():
    return [
        resolve_target,
        resolve_targets,
        resolve_target_with_origin,
        resolve_targets_with_origins,
        transitive_target,
        transitive_targets,
        find_owners,
        addresses_with_origins_from_filesystem_specs,
        resolve_sources_snapshot,
        resolve_addresses_with_origins,
        RootRule(Specs),
        RootRule(OwnersRequest),
    ]
