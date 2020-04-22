# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import PurePath
from typing import DefaultDict, List, Tuple, Union, cast

from pants.base.exceptions import ResolveError, TargetDefinitionException
from pants.base.specs import (
    AddressSpecs,
    AscendantAddresses,
    FilesystemLiteralSpec,
    FilesystemMergedSpec,
    FilesystemResolvedGlobSpec,
    FilesystemSpecs,
)
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressesWithOrigins,
    AddressWithOrigin,
    BuildFileAddress,
)
from pants.engine.fs import EMPTY_SNAPSHOT, PathGlobs, Snapshot, SourcesSnapshot, SourcesSnapshots
from pants.engine.internals.parser import HydratedStruct
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import HydratedField, HydratedTarget, HydratedTargets, logger
from pants.engine.legacy.structs import HydrateableField, SourcesField, TargetAdaptor
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import (
    Dependencies,
    RegisteredTargetTypes,
    Target,
    Targets,
    TargetsWithOrigins,
    TargetWithOrigin,
    TransitiveTarget,
    TransitiveTargets,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership
from pants.option.global_options import GlobalOptions, OwnersNotFoundBehavior
from pants.source.filespec import any_matches_filespec
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

# -----------------------------------------------------------------------------------------------
# Struct -> Target(s)
# -----------------------------------------------------------------------------------------------


@rule
async def resolve_target(
    hydrated_struct: HydratedStruct,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
) -> WrappedTarget:
    kwargs = hydrated_struct.value.kwargs().copy()
    type_alias = kwargs.pop("type_alias")

    # We special case `address` and the field `name`. The `Target` constructor requires an
    # `Address`, so we use the value pre-calculated via `build_files.py`'s `hydrate_struct` rule.
    # We throw away the field `name` because it can be accessed via `tgt.address.target_name`, so
    # there is no (known) reason to preserve the field.
    address = cast(Address, kwargs.pop("address"))
    kwargs.pop("name", None)

    # We convert `source` into `sources` because the Target API has no `Source` field, only
    # `Sources`.
    if "source" in kwargs and "sources" in kwargs:
        raise TargetDefinitionException(
            address, "Cannot specify both `source` and `sources` fields."
        )
    if "source" in kwargs:
        source = kwargs.pop("source")
        if not isinstance(source, str):
            raise TargetDefinitionException(
                address,
                f"The `source` field must be a string containing a path relative to the target, "
                f"but got {source} of type {type(source)}.",
            )
        kwargs["sources"] = [source]

    target_type = registered_target_types.aliases_to_types.get(type_alias, None)
    if target_type is None:
        raise TargetDefinitionException(
            address,
            f"Target type {repr(type_alias)} is not recognized. All valid target types: "
            f"{sorted(registered_target_types.aliases)}.",
        )

    # Not every target type has the Dependencies field registered, but the StructWithDependencies
    # code means that `kwargs` will always have an entry. We must remove `dependencies` from
    # `kwargs` for target types without the value, otherwise we'll get an "unrecognized field"
    # error. But, we also need to be careful to error if the user did explicitly specify
    # `dependencies` in the BUILD file.
    if kwargs["dependencies"] is None and not target_type.class_has_field(
        Dependencies, union_membership=union_membership
    ):
        kwargs.pop("dependencies")

    return WrappedTarget(target_type(kwargs, address=address))


@rule
async def resolve_targets(addresses: Addresses) -> Targets:
    wrapped_targets = await MultiGet(Get[WrappedTarget](Address, a) for a in addresses)
    return Targets(wrapped_target.target for wrapped_target in wrapped_targets)


# -----------------------------------------------------------------------------------------------
# AddressWithOrigin(s) -> TargetWithOrigin(s)
# -----------------------------------------------------------------------------------------------


@rule
async def resolve_target_with_origin(address_with_origin: AddressWithOrigin) -> TargetWithOrigin:
    wrapped_target = await Get[WrappedTarget](Address, address_with_origin.address)
    return TargetWithOrigin(wrapped_target.target, address_with_origin.origin)


@rule
async def resolve_targets_with_origins(
    addresses_with_origins: AddressesWithOrigins,
) -> TargetsWithOrigins:
    targets_with_origins = await MultiGet(
        Get[TargetWithOrigin](AddressWithOrigin, address_with_origin)
        for address_with_origin in addresses_with_origins
    )
    return TargetsWithOrigins(targets_with_origins)


# -----------------------------------------------------------------------------------------------
# TransitiveTargets
# -----------------------------------------------------------------------------------------------


@rule
async def transitive_target(wrapped_root: WrappedTarget) -> TransitiveTarget:
    root = wrapped_root.target
    dependencies = (
        await MultiGet(Get[TransitiveTarget](Address, d) for d in root[Dependencies].value or ())
        if root.has_field(Dependencies)
        else tuple()
    )
    return TransitiveTarget(root, dependencies)


@rule
async def transitive_targets(addresses: Addresses) -> TransitiveTargets:
    """Given Addresses, kicks off recursion on expansion of TransitiveTargets.

    The TransitiveTarget dataclass represents a structure-shared graph, which we walk and flatten
    here. The engine memoizes the computation of TransitiveTarget, so when multiple
    TransitiveTargets objects are being constructed for multiple roots, their structure will be
    shared.
    """
    transitive_targets = await MultiGet(Get[TransitiveTarget](Address, a) for a in addresses)

    closure: OrderedSet[Target] = OrderedSet()
    to_visit = deque(transitive_targets)

    while to_visit:
        tt = to_visit.popleft()
        if tt.root in closure:
            continue
        closure.add(tt.root)
        to_visit.extend(tt.dependencies)

    return TransitiveTargets(tuple(tt.root for tt in transitive_targets), FrozenOrderedSet(closure))


# -----------------------------------------------------------------------------------------------
# Find the owners of a file
# -----------------------------------------------------------------------------------------------


class InvalidOwnersOfArgs(Exception):
    pass


@dataclass(frozen=True)
class OwnersRequest:
    """A request for the owners of a set of file paths."""

    sources: Tuple[str, ...]


@dataclass(frozen=True)
class Owners:
    addresses: Addresses


@rule
async def find_owners(owners_request: OwnersRequest) -> Owners:
    sources_set = FrozenOrderedSet(owners_request.sources)
    dirs_set = FrozenOrderedSet(os.path.dirname(source) for source in sources_set)

    # Walk up the buildroot looking for targets that would conceivably claim changed sources.
    candidate_specs = tuple(AscendantAddresses(directory=d) for d in dirs_set)
    candidate_targets = await Get[HydratedTargets](AddressSpecs(candidate_specs))

    # Match the source globs against the expanded candidate targets.
    def owns_any_source(legacy_target: HydratedTarget) -> bool:
        """Given a `HydratedTarget` instance, check if it owns the given source file."""
        target_kwargs = legacy_target.adaptor.kwargs()

        # Handle `sources`-declaring targets.
        # NB: Deleted files can only be matched against the 'filespec' (ie, `PathGlobs`) for a target,
        # so we don't actually call `fileset.matches` here.
        # TODO: This matching logic should be implemented using the rust `fs` crate for two reasons:
        #  1) having two implementations isn't great
        #  2) we're expanding sources via HydratedTarget, but it isn't necessary to do that to match
        target_sources = target_kwargs.get("sources", None)
        return target_sources and any_matches_filespec(
            paths=sources_set, spec=target_sources.filespec
        )

    build_file_addresses = await MultiGet(
        Get[BuildFileAddress](Address, ht.adaptor.address) for ht in candidate_targets
    )
    owners = Addresses(
        ht.adaptor.address
        for ht, bfa in zip(candidate_targets, build_file_addresses)
        if LegacyAddressMapper.any_is_declaring_file(bfa, sources_set) or owns_any_source(ht)
    )
    return Owners(owners)


# -----------------------------------------------------------------------------------------------
# FilesystemSpecs -> Addresses
# -----------------------------------------------------------------------------------------------


@rule
async def addresses_with_origins_from_filesystem_specs(
    filesystem_specs: FilesystemSpecs, global_options: GlobalOptions,
) -> AddressesWithOrigins:
    """Find the owner(s) for each FilesystemSpec while preserving the original FilesystemSpec those
    owners come from.

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
        Get[Snapshot](PathGlobs, pg) for pg in pathglobs_per_include
    )
    owners_per_include = await MultiGet(
        Get[Owners](OwnersRequest(sources=snapshot.files)) for snapshot in snapshot_per_include
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
            and not owners.addresses
        ):
            file_path = PurePath(spec.to_spec_string())
            msg = (
                f"No owning targets could be found for the file `{file_path}`.\n\nPlease check "
                f"that there is a BUILD file in `{file_path.parent}` with a target whose `sources` field "
                f"includes `{file_path}`. See https://www.pantsbuild.org/build_files.html."
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
        for address in owners.addresses:
            addresses_to_specs[address].append(origin)
    return AddressesWithOrigins(
        AddressWithOrigin(
            address, specs[0] if len(specs) == 1 else FilesystemMergedSpec.create(specs)
        )
        for address, specs in addresses_to_specs.items()
    )


# -----------------------------------------------------------------------------------------------
# SourcesSnapshots
# -----------------------------------------------------------------------------------------------


@rule
async def hydrate_sources_snapshot(hydrated_struct: HydratedStruct) -> SourcesSnapshot:
    """Construct a SourcesSnapshot from a TargetAdaptor without hydrating any other fields."""
    target_adaptor = cast(TargetAdaptor, hydrated_struct.value)
    sources_field = next(
        (fa for fa in target_adaptor.field_adaptors if isinstance(fa, SourcesField)), None
    )
    if sources_field is None:
        return SourcesSnapshot(EMPTY_SNAPSHOT)
    hydrated_sources_field = await Get[HydratedField](HydrateableField, sources_field)
    efws = cast(EagerFilesetWithSpec, hydrated_sources_field.value)
    return SourcesSnapshot(efws.snapshot)


@rule
async def sources_snapshots_from_address_specs(address_specs: AddressSpecs) -> SourcesSnapshots:
    """Request SourcesSnapshots for the given address specs.

    Each address will map to a corresponding SourcesSnapshot. This rule avoids hydrating any other
    fields.
    """
    addresses = await Get[Addresses](AddressSpecs, address_specs)
    snapshots = await MultiGet(Get[SourcesSnapshot](Address, a) for a in addresses)
    return SourcesSnapshots(snapshots)


@rule
async def sources_snapshots_from_filesystem_specs(
    filesystem_specs: FilesystemSpecs, global_options: GlobalOptions,
) -> SourcesSnapshots:
    """Resolve the snapshot associated with the provided filesystem specs."""
    snapshot = await Get[Snapshot](
        PathGlobs,
        filesystem_specs.to_path_globs(
            global_options.options.owners_not_found_behavior.to_glob_match_error_behavior()
        ),
    )
    return SourcesSnapshots([SourcesSnapshot(snapshot)])


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
        hydrate_sources_snapshot,
        sources_snapshots_from_address_specs,
        sources_snapshots_from_filesystem_specs,
        RootRule(FilesystemSpecs),
        RootRule(OwnersRequest),
    ]
