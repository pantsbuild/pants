# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import logging
import os
from collections import defaultdict
from typing import Iterable

from pants.backend.project_info.filter_targets import FilterSubsystem
from pants.base.specs import (
    AddressLiteralSpec,
    AncestorGlobSpec,
    DirGlobSpec,
    DirLiteralSpec,
    RawSpecs,
    RawSpecsWithOnlyFileOwners,
    RawSpecsWithoutFileOwners,
    RecursiveGlobSpec,
    Specs,
)
from pants.engine.addresses import Address, Addresses, AddressInput
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.fs import PathGlobs, Paths, SpecsPaths
from pants.engine.internals.build_files import AddressFamilyDir, BuildFileOptions
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.mapper import AddressFamilies, AddressFamily, SpecsFilter
from pants.engine.internals.parametrize import (
    _TargetParametrizations,
    _TargetParametrizationsRequest,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.internals.synthetic_targets import (
    SyntheticTargetsSpecPaths,
    SyntheticTargetsSpecPathsRequest,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    FilteredTargets,
    NoApplicableTargetsBehavior,
    RegisteredTargetTypes,
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    TargetGenerator,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    Targets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionMembership
from pants.option.global_options import GlobalOptions
from pants.util.dirutil import recursive_dirname
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# RawSpecsWithoutFileOwners -> Targets
# -----------------------------------------------------------------------------------------------


async def _determine_literal_addresses_from_raw_specs(
    literal_specs: tuple[AddressLiteralSpec, ...],
    local_environment_name: ChosenLocalEnvironmentName,
    *,
    description_of_origin: str,
) -> tuple[WrappedTarget, ...]:
    literal_addresses = await MultiGet(
        Get(
            Address,
            AddressInput(
                str(spec),
                spec.path_component,
                description_of_origin=description_of_origin,
                target_component=spec.target_component,
                generated_component=spec.generated_component,
                parameters=dict(spec.parameters),
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
        Get(
            _TargetParametrizations,
            {
                _TargetParametrizationsRequest(
                    address.maybe_convert_to_target_generator(),
                    description_of_origin=description_of_origin,
                ): _TargetParametrizationsRequest,
                local_environment_name.val: EnvironmentName,
            },
        )
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
    return await MultiGet(
        Get(WrappedTarget, WrappedTargetRequest(addr, description_of_origin=description_of_origin))
        for addr in all_candidate_addresses
    )


@rule(_masked_types=[EnvironmentName])
async def address_families_from_raw_specs_without_file_owners(
    specs: RawSpecsWithoutFileOwners,
    build_file_options: BuildFileOptions,
) -> AddressFamilies:
    if not (specs.dir_literals or specs.dir_globs or specs.recursive_globs or specs.ancestor_globs):
        return AddressFamilies()
    # Resolve all globs.
    build_file_globs, validation_globs = specs.to_build_file_path_globs_tuple(
        build_patterns=build_file_options.patterns,
        build_ignore_patterns=build_file_options.ignores,
    )
    build_file_paths, _ = await MultiGet(
        Get(Paths, PathGlobs, build_file_globs),
        Get(Paths, PathGlobs, validation_globs),
    )
    dirnames = set(
        await Get(
            SyntheticTargetsSpecPaths, SyntheticTargetsSpecPathsRequest(tuple(specs.glob_specs()))
        )
    )
    dirnames.update(os.path.dirname(f) for f in build_file_paths.files)
    return AddressFamilies(
        await MultiGet(Get(AddressFamily, AddressFamilyDir(d)) for d in dirnames)
    )


@rule(_masked_types=[EnvironmentName])
async def addresses_from_raw_specs_without_file_owners(
    specs: RawSpecsWithoutFileOwners,
    specs_filter: SpecsFilter,
    local_environment_name: ChosenLocalEnvironmentName,
) -> Addresses:
    matched_addresses: OrderedSet[Address] = OrderedSet()
    filtering_disabled = specs.filter_by_global_options is False

    literal_wrapped_targets = await _determine_literal_addresses_from_raw_specs(
        specs.address_literals,
        local_environment_name,
        description_of_origin=specs.description_of_origin,
    )
    matched_addresses.update(
        wrapped_tgt.target.address
        for wrapped_tgt in literal_wrapped_targets
        if filtering_disabled or specs_filter.matches(wrapped_tgt.target)
    )

    address_families = await Get(AddressFamilies, RawSpecsWithoutFileOwners, specs)
    if not address_families:
        return Addresses(matched_addresses)

    base_addresses = address_families.addresses()

    target_parametrizations_list = await MultiGet(
        Get(
            _TargetParametrizations,
            {
                _TargetParametrizationsRequest(
                    base_address, description_of_origin=specs.description_of_origin
                ): _TargetParametrizationsRequest,
                local_environment_name.val: EnvironmentName,
            },
        )
        for base_address in base_addresses
    )
    residence_dir_to_targets = defaultdict(list)
    for target_parametrizations in target_parametrizations_list:
        for tgt in target_parametrizations.all:
            residence_dir_to_targets[tgt.residence_dir].append(tgt)

    def valid_tgt(
        tgt: Target, spec: DirLiteralSpec | DirGlobSpec | RecursiveGlobSpec | AncestorGlobSpec
    ) -> bool:
        if not spec.matches_target_generators and isinstance(tgt, TargetGenerator):
            return False
        return filtering_disabled or specs_filter.matches(tgt)

    for glob_spec in specs.glob_specs():
        for residence_dir in residence_dir_to_targets:
            if not glob_spec.matches_target_residence_dir(residence_dir):
                continue
            matched_addresses.update(
                tgt.address
                for tgt in residence_dir_to_targets[residence_dir]
                if valid_tgt(tgt, glob_spec)
            )

    return Addresses(sorted(matched_addresses))


# -----------------------------------------------------------------------------------------------
# RawSpecsWithOnlyFileOwners -> Targets
# -----------------------------------------------------------------------------------------------


@rule(_masked_types=[EnvironmentName])
async def addresses_from_raw_specs_with_only_file_owners(
    specs: RawSpecsWithOnlyFileOwners,
) -> Owners:
    """Find the owner(s) for each spec."""
    paths_per_include = await MultiGet(
        Get(Paths, PathGlobs, specs.path_globs_for_spec(spec)) for spec in specs.all_specs()
    )
    all_files = tuple(itertools.chain.from_iterable(paths.files for paths in paths_per_include))
    owners = await Get(
        Owners,
        OwnersRequest(
            all_files,
            filter_by_global_options=specs.filter_by_global_options,
            # Specifying a BUILD file should not expand to all the targets it defines.
            match_if_owning_build_file_included_in_sources=False,
        ),
    )
    return owners


@rule(_masked_types=[EnvironmentName])
async def addresses_from_owners(owners: Owners) -> Addresses:
    return Addresses(sorted(owners))


# -----------------------------------------------------------------------------------------------
# RawSpecs & Specs -> Targets
# -----------------------------------------------------------------------------------------------


@rule(_masked_types=[EnvironmentName])
async def resolve_addresses_from_raw_specs(specs: RawSpecs) -> Addresses:
    without_file_owners, with_file_owners = await MultiGet(
        Get(Addresses, RawSpecsWithoutFileOwners, RawSpecsWithoutFileOwners.from_raw_specs(specs)),
        Get(
            Addresses, RawSpecsWithOnlyFileOwners, RawSpecsWithOnlyFileOwners.from_raw_specs(specs)
        ),
    )
    # Use a set to dedupe.
    return Addresses(sorted({*without_file_owners, *with_file_owners}))


@rule(desc="Find targets from input specs", level=LogLevel.DEBUG, _masked_types=[EnvironmentName])
async def resolve_addresses_from_specs(specs: Specs) -> Addresses:
    includes, ignores = await MultiGet(
        Get(Addresses, RawSpecs, specs.includes),
        Get(Addresses, RawSpecs, specs.ignores),
    )
    # No matter what, ignores win out over includes. This avoids "specificity wars" and keeps our
    # semantics simple/predictable.
    return Addresses(FrozenOrderedSet(includes) - FrozenOrderedSet(ignores))


@rule(_masked_types=[EnvironmentName])
def filter_targets(targets: Targets, specs_filter: SpecsFilter) -> FilteredTargets:
    return FilteredTargets(tgt for tgt in targets if specs_filter.matches(tgt))


@rule
def setup_specs_filter(
    global_options: GlobalOptions,
    filter_subsystem: FilterSubsystem,
    registered_target_types: RegisteredTargetTypes,
) -> SpecsFilter:
    return SpecsFilter.create(filter_subsystem, registered_target_types, tags=global_options.tag)


# -----------------------------------------------------------------------------------------------
# SpecsPaths
# -----------------------------------------------------------------------------------------------


@rule(desc="Find all sources from input specs", level=LogLevel.DEBUG)
async def resolve_specs_paths(specs: Specs) -> SpecsPaths:
    """Resolve all files matching the given specs.

    All matched targets will use their `sources` field. Certain specs like FileLiteralSpec will
    also match against all their files, regardless of if a target owns them.

    Ignores win out over includes, with these edge cases:

    * Ignored paths: the resolved paths should be excluded.
    * Ignored targets: their `sources` should be excluded.
    * File owned by a target that gets filtered out, e.g. via `--tag`. See
      https://github.com/pantsbuild/pants/issues/15478.
    """

    unfiltered_include_targets, ignore_targets, include_paths, ignore_paths = await MultiGet(
        Get(Targets, RawSpecs, dataclasses.replace(specs.includes, filter_by_global_options=False)),
        Get(Targets, RawSpecs, specs.ignores),
        Get(Paths, PathGlobs, specs.includes.to_specs_paths_path_globs()),
        Get(Paths, PathGlobs, specs.ignores.to_specs_paths_path_globs()),
    )

    filtered_include_targets = await Get(FilteredTargets, Targets, unfiltered_include_targets)
    include_targets_sources_paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt[SourcesField]))
        for tgt in filtered_include_targets
        if tgt.has_field(SourcesField)
    )

    ignore_targets_sources_paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt[SourcesField]))
        for tgt in ignore_targets
        if tgt.has_field(SourcesField)
    )

    result_paths = OrderedSet(
        itertools.chain.from_iterable(paths.files for paths in include_targets_sources_paths),
    )
    result_paths.update(include_paths.files)
    result_paths.difference_update(
        itertools.chain.from_iterable(paths.files for paths in ignore_targets_sources_paths)
    )
    result_paths.difference_update(ignore_paths.files)

    # If include paths were given, we need to also remove any paths from filtered out targets
    # (e.g. via `--tag`), per https://github.com/pantsbuild/pants/issues/15478.
    if include_paths.files:
        filtered_out_include_targets = FrozenOrderedSet(unfiltered_include_targets).difference(
            FrozenOrderedSet(filtered_include_targets)
        )
        filtered_include_targets_sources_paths = await MultiGet(
            Get(SourcesPaths, SourcesPathsRequest(tgt[SourcesField]))
            for tgt in filtered_out_include_targets
            if tgt.has_field(SourcesField)
        )
        result_paths.difference_update(
            itertools.chain.from_iterable(
                paths.files for paths in filtered_include_targets_sources_paths
            )
        )

    dirs = OrderedSet(
        itertools.chain.from_iterable(recursive_dirname(os.path.dirname(f)) for f in result_paths)
    ) - {""}
    return SpecsPaths(tuple(sorted(result_paths)), tuple(sorted(dirs)))


# -----------------------------------------------------------------------------------------------
# RawSpecs -> FieldSets
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
            specs_description = specs.arguments_provided_description() or ""
            if specs_description:
                specs_description = f" {specs_description} with"
            msg += (
                f"However, you only specified{specs_description} these target types:\n\n"
                f"{bullet_list(inapplicable_target_aliases)}\n\n"
            )

        # Add a remedy.
        #
        # We sometimes suggest using `./pants filedeps` to find applicable files. However, this
        # command only works if at least one of the targets has a SourcesField field.
        filedeps_goal_works = any(
            tgt.class_has_field(SourcesField, union_membership) for tgt in applicable_target_types
        )
        pants_filter_command = (
            f"{bin_name()} --filter-target-type={','.join(applicable_target_aliases)}"
        )
        remedy = (
            f"Please specify relevant file and/or target arguments. Run `{pants_filter_command} "
            f"list ::` to find all applicable targets in your project"
        )
        if filedeps_goal_works:
            remedy += f", or run `{pants_filter_command} filedeps ::` to find all applicable files."
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
    targets = await Get(FilteredTargets, Specs, specs)
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

        # We squelch the warning if the specs came from change detection or only from globs,
        # since in that case we interpret the user's intent as "if there are relevant matching
        # targets, act on them". But we still want to warn if the specs were literal, or empty.
        #
        # No need to check `specs.ignores` here, as change detection will not set that. Likewise,
        # we don't want an ignore spec to trigger this warning, even if it was a literal.
        empty_ok = specs.includes.from_change_detection or (
            specs.includes
            and not specs.includes.address_literals
            and not specs.includes.file_literals
        )
        if (
            request.no_applicable_targets_behavior == NoApplicableTargetsBehavior.warn
            and not empty_ok
        ):
            logger.warning(str(no_applicable_exception))

    if request.num_shards > 0:
        sharded_targets_to_applicable_field_sets = {
            tgt: value
            for tgt, value in targets_to_applicable_field_sets.items()
            if request.is_in_shard(tgt.address.spec)
        }
        return TargetRootsToFieldSets(sharded_targets_to_applicable_field_sets)
    return TargetRootsToFieldSets(targets_to_applicable_field_sets)


def rules():
    return collect_rules()
