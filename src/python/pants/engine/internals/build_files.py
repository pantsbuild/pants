# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from typing import Any, Dict

from pants.base.exceptions import ResolveError
from pants.base.project_tree import Dir
from pants.base.specs import AddressSpec, AddressSpecs
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressesWithOrigins,
    AddressInput,
    AddressWithOrigin,
    BuildFileAddress,
    BuildFileAddresses,
)
from pants.engine.fs import DigestContents, GlobMatchErrorBehavior, PathGlobs, Snapshot
from pants.engine.internals.mapper import (
    AddressFamily,
    AddressMap,
    AddressMapper,
    AddressSpecsFilter,
)
from pants.engine.internals.parser import BuildFilePreludeSymbols, error_on_imports
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.option.global_options import GlobalOptions
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet


@rule
async def evaluate_preludes(address_mapper: AddressMapper) -> BuildFilePreludeSymbols:
    prelude_digest_contents = await Get(
        DigestContents,
        PathGlobs(
            address_mapper.prelude_glob_patterns,
            glob_match_error_behavior=GlobMatchErrorBehavior.ignore,
        ),
    )
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
async def resolve_address(address_input: AddressInput) -> Address:
    # Determine the type of the path_component of the input.
    if address_input.path_component:
        snapshot = await Get(Snapshot, PathGlobs(globs=(address_input.path_component,)))
        is_file, is_dir = bool(snapshot.files), bool(snapshot.dirs)
    else:
        # It is an address in the root directory.
        is_file, is_dir = False, True

    if is_file:
        return address_input.file_to_address()
    elif is_dir:
        return address_input.dir_to_address()
    else:
        spec = address_input.path_component
        if address_input.target_component:
            spec += f":{address_input.target_component}"
        raise ResolveError(
            f"The file or directory '{address_input.path_component}' does not exist on disk in the "
            f"workspace, so the address '{spec}' cannot be resolved."
        )


@rule
async def parse_address_family(
    address_mapper: AddressMapper, prelude_symbols: BuildFilePreludeSymbols, directory: Dir
) -> AddressFamily:
    """Given an AddressMapper and a directory, return an AddressFamily.

    The AddressFamily may be empty, but it will not be None.
    """
    digest_contents = await Get(
        DigestContents,
        PathGlobs(
            globs=(
                *(os.path.join(directory.path, p) for p in address_mapper.build_patterns),
                *(f"!{p}" for p in address_mapper.build_ignore_patterns),
            )
        ),
    )
    if not digest_contents:
        raise ResolveError(f"Directory '{directory.path}' does not contain any BUILD files.")

    address_maps = [
        AddressMap.parse(fc.path, fc.content.decode(), address_mapper.parser, prelude_symbols)
        for fc in digest_contents
    ]
    return AddressFamily.create(directory.path, address_maps)


@rule
async def find_build_file(address: Address) -> BuildFileAddress:
    address_family = await Get(AddressFamily, Dir(address.spec_path))
    owning_address = address.maybe_convert_to_base_target()
    if address_family.get_target_adaptor(owning_address) is None:
        raise ResolveError.did_you_mean(
            bad_name=owning_address.target_name,
            known_names=address_family.target_names,
            namespace=address_family.namespace,
        )
    bfa = next(
        build_file_address
        for build_file_address in address_family.build_file_addresses
        if build_file_address.address == owning_address
    )
    return (
        bfa if address.is_base_target else BuildFileAddress(rel_path=bfa.rel_path, address=address)
    )


@rule
async def find_build_files(addresses: Addresses) -> BuildFileAddresses:
    bfas = await MultiGet(Get(BuildFileAddress, Address, address) for address in addresses)
    return BuildFileAddresses(bfas)


@rule
async def find_target_adaptor(address: Address) -> TargetAdaptor:
    """Hydrate a TargetAdaptor so that it may be converted into the Target API."""
    if not address.is_base_target:
        raise ValueError(
            f"Subtargets are not resident in BUILD files, and so do not have TargetAdaptors: {address}"
        )
    address_family = await Get(AddressFamily, Dir(address.spec_path))
    target_adaptor = address_family.get_target_adaptor(address)
    if target_adaptor is None:
        raise ResolveError.did_you_mean(
            bad_name=address.target_name,
            known_names=address_family.target_names,
            namespace=address_family.namespace,
        )
    return target_adaptor


@rule
def setup_address_specs_filter(global_options: GlobalOptions) -> AddressSpecsFilter:
    opts = global_options.options
    return AddressSpecsFilter(tags=opts.tag, exclude_target_regexps=opts.exclude_target_regexp)


@rule
async def addresses_with_origins_from_address_specs(
    address_specs: AddressSpecs, address_mapper: AddressMapper, specs_filter: AddressSpecsFilter
) -> AddressesWithOrigins:
    """Given an AddressMapper and list of AddressSpecs, return matching AddressesWithOrigins.

    :raises: :class:`ResolveError` if the provided specs fail to match targets, and those spec
        types expect to have matched something.
    """
    # Snapshot all BUILD files covered by the AddressSpecs, then group by directory.
    snapshot = await Get(
        Snapshot,
        PathGlobs,
        address_specs.to_path_globs(
            build_patterns=address_mapper.build_patterns,
            build_ignore_patterns=address_mapper.build_ignore_patterns,
        ),
    )
    dirnames = {os.path.dirname(f) for f in snapshot.files}
    address_families = await MultiGet(Get(AddressFamily, Dir(d)) for d in dirnames)
    address_family_by_directory = {af.namespace: af for af in address_families}

    matched_addresses: OrderedSet[Address] = OrderedSet()
    addr_to_origin: Dict[Address, AddressSpec] = {}

    for address_spec in address_specs:
        # These may raise ResolveError, depending on the type of spec.
        addr_families_for_spec = address_spec.matching_address_families(address_family_by_directory)
        addr_target_pairs_for_spec = address_spec.matching_addresses(addr_families_for_spec)

        for addr, _ in addr_target_pairs_for_spec:
            # A target might be covered by multiple specs, so we take the most specific one.
            addr_to_origin[addr] = AddressSpecs.more_specific(
                addr_to_origin.get(addr), address_spec
            )

        matched_addresses.update(
            addr
            for (addr, tgt) in addr_target_pairs_for_spec
            if address_specs.filter_by_global_options is False or specs_filter.matches(addr, tgt)
        )

    return AddressesWithOrigins(
        AddressWithOrigin(address=addr, origin=addr_to_origin[addr]) for addr in matched_addresses
    )


@rule
def strip_address_origins(addresses_with_origins: AddressesWithOrigins) -> Addresses:
    return Addresses(address_with_origin.address for address_with_origin in addresses_with_origins)


def rules():
    return collect_rules()
