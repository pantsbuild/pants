# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
import os
from collections import defaultdict
from pathlib import PurePath

from pants.base.exceptions import ResolveError
from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpecs,
    FileLiteralSpec,
    FilesystemSpecs,
    Specs,
)
from pants.engine.addresses import Address, Addresses, AddressInput
from pants.engine.fs import PathGlobs, Paths, SpecsSnapshot
from pants.engine.internals.build_files import AddressFamilyDir, BuildFileOptions
from pants.engine.internals.graph import Owners, OwnersRequest, _log_or_raise_unmatched_owners
from pants.engine.internals.mapper import AddressFamily, SpecsFilter
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.internals.parametrize import _TargetParametrizations
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule, rule_helper
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Targets,
    WrappedTarget,
)
from pants.option.global_options import GlobalOptions, OwnersNotFoundBehavior
from pants.util.docutil import bin_name, doc_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


@rule
def setup_specs_filter(global_options: GlobalOptions) -> SpecsFilter:
    return SpecsFilter(
        tags=global_options.tag, exclude_target_regexps=global_options.exclude_target_regexp
    )


@rule_helper
async def _determine_literal_addresses_from_specs(
    literal_specs: tuple[AddressLiteralSpec, ...]
) -> tuple[WrappedTarget, ...]:
    literal_addresses = await MultiGet(
        Get(
            Address,
            AddressInput(
                spec.path_component,
                spec.target_component,
                spec.generated_component,
                spec.parameters,
            ),
        )
        for spec in literal_specs
    )

    # We replace references to parametrized target templates with all their created targets. For
    # example:
    #  - dir:tgt -> (dir:tgt@k=v1, dir:tgt@k=v2)
    #  - dir:tgt@k=v -> (dir:tgt@k=v,another=a, dir:tgt@k=v,another=b), but not anything
    #       where @k=v is not true.
    literal_parametrizations = await MultiGet(
        Get(_TargetParametrizations, Address, address.maybe_convert_to_target_generator())
        for address in literal_addresses
    )

    # Note that if the address is not in the _TargetParametrizations, we must fall back to that
    # address's value. This will allow us to error that the address is invalid.
    all_candidate_addresses = itertools.chain.from_iterable(
        list(params.get_all_superset_targets(address)) or [address]
        for address, params in zip(literal_addresses, literal_parametrizations)
    )

    # We eagerly call the `WrappedTarget` rule because it will validate that every final address
    # actually exists, such as with generated target addresses.
    return await MultiGet(Get(WrappedTarget, Address, addr) for addr in all_candidate_addresses)


@rule
async def addresses_from_address_specs(
    address_specs: AddressSpecs,
    build_file_options: BuildFileOptions,
    specs_filter: SpecsFilter,
) -> Addresses:
    matched_addresses: OrderedSet[Address] = OrderedSet()
    filtering_disabled = address_specs.filter_by_global_options is False

    literal_wrapped_targets = await _determine_literal_addresses_from_specs(address_specs.literals)
    matched_addresses.update(
        wrapped_tgt.target.address
        for wrapped_tgt in literal_wrapped_targets
        if filtering_disabled or specs_filter.matches(wrapped_tgt.target)
    )
    if not address_specs.globs:
        return Addresses(matched_addresses)

    # Resolve all `AddressGlobSpecs`.
    build_file_paths = await Get(
        Paths,
        PathGlobs,
        address_specs.to_build_file_path_globs(
            build_patterns=build_file_options.patterns,
            build_ignore_patterns=build_file_options.ignores,
        ),
    )
    dirnames = {os.path.dirname(f) for f in build_file_paths.files}
    address_families = await MultiGet(Get(AddressFamily, AddressFamilyDir(d)) for d in dirnames)
    base_addresses = Addresses(
        itertools.chain.from_iterable(
            address_family.addresses_to_target_adaptors for address_family in address_families
        )
    )

    target_parametrizations_list = await MultiGet(
        Get(_TargetParametrizations, Address, base_address) for base_address in base_addresses
    )
    residence_dir_to_targets = defaultdict(list)
    for target_parametrizations in target_parametrizations_list:
        for tgt in target_parametrizations.all:
            residence_dir_to_targets[tgt.residence_dir].append(tgt)

    matched_globs = set()
    for glob_spec in address_specs.globs:
        for residence_dir in residence_dir_to_targets:
            if not glob_spec.matches(residence_dir):
                continue
            matched_globs.add(glob_spec)
            matched_addresses.update(
                tgt.address
                for tgt in residence_dir_to_targets[residence_dir]
                if filtering_disabled or specs_filter.matches(tgt)
            )

    unmatched_globs = [
        glob
        for glob in address_specs.globs
        if glob not in matched_globs and glob.error_if_no_matches
    ]
    if unmatched_globs:
        glob_description = (
            f"the address glob `{unmatched_globs[0]}`"
            if len(unmatched_globs) == 1
            else f"these address globs: {sorted(str(glob) for glob in unmatched_globs)}"
        )
        raise ResolveError(
            f"No targets found for {glob_description}\n\n"
            f"Do targets exist in those directories? Maybe run `{bin_name()} tailor` to generate "
            f"BUILD files? See {doc_url('targets')} about targets and BUILD files."
        )

    return Addresses(sorted(matched_addresses))


@rule
def extract_owners_not_found_behavior(global_options: GlobalOptions) -> OwnersNotFoundBehavior:
    return global_options.owners_not_found_behavior


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
        Get(Owners, OwnersRequest(paths.files, filter_by_global_options=True))
        for paths in paths_per_include
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


def rules():
    return collect_rules()
