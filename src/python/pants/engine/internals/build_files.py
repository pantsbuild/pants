# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os.path
from typing import Any, Dict, cast

from pants.base.exceptions import ResolveError
from pants.base.project_tree import Dir
from pants.base.specs import AddressSpec, AddressSpecs, SingleAddress, more_specific
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressesWithOrigins,
    AddressWithOrigin,
    BuildFileAddress,
    BuildFileAddresses,
)
from pants.engine.fs import Digest, DigestContents, PathGlobs, Snapshot
from pants.engine.internals.mapper import AddressFamily, AddressMap, AddressMapper
from pants.engine.internals.parser import BuildFilePreludeSymbols, error_on_imports
from pants.engine.internals.struct import HydratedTargetAdaptor, TargetAdaptor
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.option.global_options import GlobMatchErrorBehavior
from pants.util.frozendict import FrozenDict
from pants.util.objects import TypeConstraintError
from pants.util.ordered_set import OrderedSet


class ResolvedTypeMismatchError(ResolveError):
    """Indicates a resolved object was not of the expected type."""


@rule
async def evaluate_preludes(address_mapper: AddressMapper) -> BuildFilePreludeSymbols:
    snapshot = await Get(
        Snapshot,
        PathGlobs(
            address_mapper.prelude_glob_patterns,
            glob_match_error_behavior=GlobMatchErrorBehavior.ignore,
        ),
    )
    prelude_digest_contents = await Get(DigestContents, Digest, snapshot.digest)
    values: Dict[str, Any] = {}
    for file_content in prelude_digest_contents:
        try:
            file_content_str = file_content.content.decode()
            content = compile(file_content_str, file_content.path, "exec")
            exec(content, values)
        except Exception as e:
            raise Exception(f"Error parsing prelude file {file_content.path}: {e}")
        error_on_imports(file_content_str, file_content.path)
    # __builtins__ is a dict, so isn't hashable, and can't be put in a FrozenDict.
    # Fortunately, we don't care about it - preludes should not be able to override builtins, so we just pop it out.
    # TODO: Give a nice error message if a prelude tries to set a expose a non-hashable value.
    values.pop("__builtins__", None)
    return BuildFilePreludeSymbols(FrozenDict(values))


@rule
async def parse_address_family(
    address_mapper: AddressMapper, prelude_symbols: BuildFilePreludeSymbols, directory: Dir
) -> AddressFamily:
    """Given an AddressMapper and a directory, return an AddressFamily.

    The AddressFamily may be empty, but it will not be None.
    """
    path_globs = PathGlobs(
        globs=(
            *(os.path.join(directory.path, p) for p in address_mapper.build_patterns),
            *(f"!{p}" for p in address_mapper.build_ignore_patterns),
        )
    )
    snapshot = await Get(Snapshot, PathGlobs, path_globs)
    digest_contents = await Get(DigestContents, Digest, snapshot.digest)
    if not digest_contents:
        raise ResolveError(f"Directory '{directory.path}' does not contain any BUILD files.")

    address_maps = [
        AddressMap.parse(fc.path, fc.content.decode(), address_mapper.parser, prelude_symbols)
        for fc in digest_contents
    ]
    return AddressFamily.create(directory.path, address_maps)


def _raise_did_you_mean(address_family: AddressFamily, name: str, source=None) -> None:
    names = [a.target_name for a in address_family.addressables]
    possibilities = "\n  ".join(":{}".format(target_name) for target_name in sorted(names))

    resolve_error = ResolveError(
        f"'{name}' was not found in namespace '{address_family.namespace}'. Did you mean one "
        f"of:\n  {possibilities}"
    )

    if source:
        raise resolve_error from source
    raise resolve_error


@rule
async def find_build_file(address: Address) -> BuildFileAddress:
    address_family = await Get(AddressFamily, Dir(address.spec_path))
    owning_address = (
        address
        if not address.generated_base_target_name
        else Address(address.spec_path, address.generated_base_target_name)
    )
    if owning_address not in address_family.addressables:
        _raise_did_you_mean(address_family=address_family, name=owning_address.target_name)
    bfa = next(
        build_file_address
        for build_file_address in address_family.addressables.keys()
        if build_file_address == owning_address
    )
    return (
        bfa
        if not address.generated_base_target_name
        else BuildFileAddress(
            rel_path=bfa.rel_path,
            target_name=address.target_name,
            generated_base_target_name=address.generated_base_target_name,
        )
    )


@rule
async def find_build_files(addresses: Addresses) -> BuildFileAddresses:
    bfas = await MultiGet(Get(BuildFileAddress, Address, address) for address in addresses)
    return BuildFileAddresses(bfas)


@rule
async def hydrate_target_adaptor(address: Address) -> HydratedTargetAdaptor:
    """Hydrate a TargetAdaptor so that it may be converted into the Target API."""
    address_family = await Get(AddressFamily, Dir(address.spec_path))
    target_adaptor = address_family.addressables_as_address_keyed.get(address)
    if target_adaptor is None:
        _raise_did_you_mean(address_family, address.target_name)

    target_adaptor = cast(TargetAdaptor, target_adaptor)

    hydrated_args = {"address": address, **target_adaptor._asdict()}
    try:
        target_adaptor = TargetAdaptor(**hydrated_args)
    except TypeConstraintError as e:
        raise ResolvedTypeMismatchError(e)
    target_adaptor = cast(TargetAdaptor, target_adaptor.create())
    target_adaptor.validate()
    return HydratedTargetAdaptor(target_adaptor)


@rule
async def addresses_with_origins_from_address_specs(
    address_mapper: AddressMapper, address_specs: AddressSpecs,
) -> AddressesWithOrigins:
    """Given an AddressMapper and list of AddressSpecs, return matching AddressesWithOrigins.

    :raises: :class:`ResolveError` if:
       - there were no matching AddressFamilies, or
       - the AddressSpec matches no addresses for SingleAddresses.
    :raises: :class:`AddressLookupError` if no targets are matched for non-SingleAddress specs.
    """
    # Capture a Snapshot covering all paths for these AddressSpecs, then group by directory.
    include_patterns = set(
        itertools.chain.from_iterable(
            address_spec.make_glob_patterns(address_mapper) for address_spec in address_specs
        )
    )
    snapshot = await Get(
        Snapshot,
        PathGlobs(
            globs=(*include_patterns, *(f"!{p}" for p in address_mapper.build_ignore_patterns))
        ),
    )
    dirnames = {os.path.dirname(f) for f in snapshot.files}
    address_families = await MultiGet(Get(AddressFamily, Dir(d)) for d in dirnames)
    address_family_by_directory = {af.namespace: af for af in address_families}

    matched_addresses: OrderedSet[Address] = OrderedSet()
    addr_to_origin: Dict[Address, AddressSpec] = {}

    for address_spec in address_specs:
        # NB: if an address spec is provided which expands to some number of targets, but those
        # targets match --exclude-target-regexp, we do NOT fail! This is why we wait to apply the
        # tag and exclude patterns until we gather all the targets the address spec would have
        # matched without them.
        try:
            addr_families_for_spec = address_spec.matching_address_families(
                address_family_by_directory
            )
        except AddressSpec.AddressFamilyResolutionError as e:
            raise ResolveError(e) from e

        try:
            all_bfaddr_tgt_pairs = address_spec.address_target_pairs_from_address_families(
                addr_families_for_spec
            )
            for bfaddr, _ in all_bfaddr_tgt_pairs:
                addr = bfaddr.to_address()
                # A target might be covered by multiple specs, so we take the most specific one.
                addr_to_origin[addr] = more_specific(addr_to_origin.get(addr), address_spec)
        except AddressSpec.AddressResolutionError as e:
            raise AddressLookupError(e) from e
        except SingleAddress._SingleAddressResolutionError as e:
            _raise_did_you_mean(e.single_address_family, e.name, source=e)

        matched_addresses.update(
            bfaddr.to_address()
            for (bfaddr, tgt) in all_bfaddr_tgt_pairs
            if address_specs.matcher.matches_target_address_pair(bfaddr, tgt)
        )

    # NB: This may be empty, as the result of filtering by tag and exclude patterns!
    return AddressesWithOrigins(
        AddressWithOrigin(address=addr, origin=addr_to_origin[addr]) for addr in matched_addresses
    )


@rule
def strip_address_origins(addresses_with_origins: AddressesWithOrigins) -> Addresses:
    return Addresses(address_with_origin.address for address_with_origin in addresses_with_origins)


def create_graph_rules(address_mapper: AddressMapper):
    """Creates tasks used to parse targets from BUILD files."""

    @rule
    def address_mapper_singleton() -> AddressMapper:
        return address_mapper

    return [
        address_mapper_singleton,
        # BUILD file parsing.
        hydrate_target_adaptor,
        parse_address_family,
        find_build_file,
        find_build_files,
        evaluate_preludes,
        # AddressSpec handling: locate directories that contain build files, and request
        # AddressFamilies for each of them.
        addresses_with_origins_from_address_specs,
        strip_address_origins,
        # Root rules representing parameters that might be provided via root subjects.
        RootRule(Address),
        RootRule(AddressWithOrigin),
        RootRule(AddressSpecs),
    ]
