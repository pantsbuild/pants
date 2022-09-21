# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import itertools
import logging
import os.path
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Iterator, NamedTuple, Sequence, cast

from pants.base.deprecated import resolve_conflicting_options, warn_or_error
from pants.base.specs import AncestorGlobSpec, RawSpecsWithoutFileOwners, RecursiveGlobSpec
from pants.build_graph.address import BuildFileAddressRequest, MaybeAddress, ResolveError
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressInput,
    BuildFileAddress,
    UnparsedAddressInputs,
)
from pants.engine.collection import Collection
from pants.engine.fs import EMPTY_SNAPSHOT, GlobMatchErrorBehavior, PathGlobs, Paths, Snapshot
from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import AddressParseException
from pants.engine.internals.parametrize import Parametrize, _TargetParametrization
from pants.engine.internals.parametrize import (  # noqa: F401
    _TargetParametrizations as _TargetParametrizations,
)
from pants.engine.internals.parametrize import (  # noqa: F401
    _TargetParametrizationsRequest as _TargetParametrizationsRequest,
)
from pants.engine.internals.target_adaptor import TargetAdaptor, TargetAdaptorRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule, rule_helper
from pants.engine.target import (
    AllTargets,
    AllTargetsRequest,
    AllUnexpandedTargets,
    CoarsenedTarget,
    CoarsenedTargets,
    CoarsenedTargetsRequest,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    Field,
    FieldDefaultFactoryRequest,
    FieldDefaultFactoryResult,
    FieldDefaults,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    FilteredTargets,
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
    InvalidFieldException,
    MultipleSourcesField,
    OverridesField,
    RegisteredTargetTypes,
    SecondaryOwnerMixin,
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    SpecialCasedDependencies,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
    TargetGenerator,
    Targets,
    TargetTypesToGenerateTargetsRequests,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
    UnrecognizedTargetTypeException,
    ValidatedDependencies,
    ValidateDependenciesRequest,
    WrappedTarget,
    WrappedTargetRequest,
    _generate_file_level_targets,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import (
    GlobalOptions,
    OwnersNotFoundBehavior,
    UnmatchedBuildFileGlobs,
)
from pants.util.docutil import bin_name, doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import bullet_list, pluralize, softwrap

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Address -> Target(s)
# -----------------------------------------------------------------------------------------------


@rule
async def resolve_unexpanded_targets(addresses: Addresses) -> UnexpandedTargets:
    wrapped_targets = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(
                a,
                # Idiomatic rules should not be manually constructing `Addresses`. Instead, they
                # should use `UnparsedAddressInputs` or `Specs` rules.
                #
                # It is technically more correct for us to require callers of
                # `Addresses -> UnexpandedTargets` to specify a `description_of_origin`. But in
                # practice, this dramatically increases boilerplate, and it should never be
                # necessary.
                #
                # Note that this contrasts with an individual `Address`, which often is unverified
                # because it can come from the rule `AddressInput -> Address`, which only verifies
                # that it has legal syntax and does not check the address exists.
                description_of_origin="<infallible>",
            ),
        )
        for a in addresses
    )
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


@memoized
def warn_deprecated_target_type(tgt_type: type[Target]) -> None:
    assert tgt_type.deprecated_alias_removal_version is not None
    warn_or_error(
        removal_version=tgt_type.deprecated_alias_removal_version,
        entity=f"the target name {tgt_type.deprecated_alias}",
        hint=(
            f"Instead, use `{tgt_type.alias}`, which behaves the same. Run `{bin_name()} "
            "update-build-files` to automatically fix your BUILD files."
        ),
    )


@memoized
def warn_deprecated_field_type(field_type: type[Field]) -> None:
    assert field_type.deprecated_alias_removal_version is not None
    warn_or_error(
        removal_version=field_type.deprecated_alias_removal_version,
        entity=f"the field name {field_type.deprecated_alias}",
        hint=(
            f"Instead, use `{field_type.alias}`, which behaves the same. Run `{bin_name()} "
            "update-build-files` to automatically fix your BUILD files."
        ),
    )


@rule
async def resolve_target_parametrizations(
    request: _TargetParametrizationsRequest,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    unmatched_build_file_globs: UnmatchedBuildFileGlobs,
) -> _TargetParametrizations:
    address = request.address

    target_adaptor = await Get(
        TargetAdaptor,
        TargetAdaptorRequest(address, description_of_origin=request.description_of_origin),
    )
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
        warn_deprecated_target_type(target_type)

    target = None
    parametrizations: list[_TargetParametrization] = []
    generate_request: type[GenerateTargetsRequest] | None = None
    if issubclass(target_type, TargetGenerator):
        generate_request = target_types_to_generate_requests.request_for(target_type)
    if generate_request:
        # Split out the `propagated_fields` before construction.
        generator_fields = dict(target_adaptor.kwargs)
        template_fields = {}
        if issubclass(target_type, TargetGenerator):
            copied_fields = (
                *target_type.copied_fields,
                *target_type._find_plugin_fields(union_membership),
            )
            for field_type in copied_fields:
                field_value = generator_fields.get(field_type.alias, None)
                if field_value is not None:
                    template_fields[field_type.alias] = field_value
            for field_type in target_type.moved_fields:
                field_value = generator_fields.pop(field_type.alias, None)
                if field_value is not None:
                    template_fields[field_type.alias] = field_value

        field_type_aliases = target_type._get_field_aliases_to_field_types(
            target_type.class_field_types(union_membership)
        ).keys()
        generator_fields_parametrized = {
            name
            for name, field in generator_fields.items()
            if isinstance(field, Parametrize) and name in field_type_aliases
        }
        if generator_fields_parametrized:
            noun = pluralize(len(generator_fields_parametrized), "field", include_count=False)
            generator_fields_parametrized_text = ", ".join(
                repr(f) for f in generator_fields_parametrized
            )
            raise InvalidFieldException(
                f"Only fields which will be moved to generated targets may be parametrized, "
                f"so target generator {address} (with type {target_type.alias}) cannot "
                f"parametrize the {generator_fields_parametrized_text} {noun}."
            )

        base_generator = target_type(
            generator_fields,
            address,
            name_explicitly_set=target_adaptor.name_explicitly_set,
            union_membership=union_membership,
        )

        overrides = {}
        if base_generator.has_field(OverridesField):
            overrides_field = base_generator[OverridesField]
            overrides_flattened = overrides_field.flatten()
            if issubclass(target_type, TargetFilesGenerator):
                override_globs = OverridesField.to_path_globs(
                    address, overrides_flattened, unmatched_build_file_globs
                )
                override_paths = await MultiGet(
                    Get(Paths, PathGlobs, path_globs) for path_globs in override_globs
                )
                overrides = OverridesField.flatten_paths(
                    address,
                    zip(override_paths, override_globs, overrides_flattened.values()),
                )
            else:
                overrides = overrides_field.flatten()

        generators = [
            (
                target_type(
                    generator_fields,
                    address,
                    name_explicitly_set=target_adaptor.name is not None,
                    union_membership=union_membership,
                ),
                template,
            )
            for address, template in Parametrize.expand(address, template_fields)
        ]
        all_generated = await MultiGet(
            Get(
                GeneratedTargets,
                GenerateTargetsRequest,
                generate_request(
                    generator,
                    template_address=generator.address,
                    template=template,
                    overrides={
                        name: dict(Parametrize.expand(generator.address, override))
                        for name, override in overrides.items()
                    },
                ),
            )
            for generator, template in generators
        )
        parametrizations.extend(
            _TargetParametrization(generator, generated_batch)
            for generated_batch, (generator, _) in zip(all_generated, generators)
        )
    else:
        first, *rest = Parametrize.expand(address, target_adaptor.kwargs)
        if rest:
            # The target was parametrized, and so the original Target does not exist.
            generated = FrozenDict(
                (
                    parameterized_address,
                    target_type(
                        parameterized_fields,
                        parameterized_address,
                        name_explicitly_set=target_adaptor.name_explicitly_set,
                        union_membership=union_membership,
                    ),
                )
                for parameterized_address, parameterized_fields in (first, *rest)
            )
            parametrizations.append(_TargetParametrization(None, generated))
        else:
            # The target was not parametrized.
            target = target_type(
                target_adaptor.kwargs,
                address,
                name_explicitly_set=target_adaptor.name_explicitly_set,
                union_membership=union_membership,
            )
            parametrizations.append(_TargetParametrization(target, FrozenDict()))

    # TODO: Move to Target constructor.
    for field_type in target.field_types if target else ():
        if (
            field_type.deprecated_alias is not None
            and field_type.deprecated_alias in target_adaptor.kwargs
        ):
            warn_deprecated_field_type(field_type)

    return _TargetParametrizations(parametrizations)


@rule
async def resolve_target(
    request: WrappedTargetRequest,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
) -> WrappedTarget:
    address = request.address
    base_address = address.maybe_convert_to_target_generator()
    parametrizations = await Get(
        _TargetParametrizations,
        _TargetParametrizationsRequest(
            base_address, description_of_origin=request.description_of_origin
        ),
    )
    target = parametrizations.get(address, target_types_to_generate_requests)
    if target is None:
        raise ResolveError(
            softwrap(
                f"""
                The address `{address}` from {request.description_of_origin} was not generated by
                the target `{base_address}`. Did you mean one of these addresses?

                {bullet_list(str(t.address) for t in parametrizations.all)}
                """
            )
        )
    return WrappedTarget(target)


@rule
async def resolve_targets(
    targets: UnexpandedTargets,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
) -> Targets:
    # Replace all generating targets with what they generate. Otherwise, keep them. If a target
    # generator does not generate any targets, keep the target generator.
    # TODO: This method does not preserve the order of inputs.
    expanded_targets: OrderedSet[Target] = OrderedSet()
    generator_targets = []
    parametrizations_gets = []
    for tgt in targets:
        if (
            target_types_to_generate_requests.is_generator(tgt)
            and not tgt.address.is_generated_target
        ):
            generator_targets.append(tgt)
            parametrizations_gets.append(
                Get(
                    _TargetParametrizations,
                    _TargetParametrizationsRequest(
                        tgt.address.maybe_convert_to_target_generator(),
                        # Idiomatic rules should not be manually creating `UnexpandedTargets`, so
                        # we can be confident that the targets actually exist and the addresses
                        # are already legitimate.
                        description_of_origin="<infallible>",
                    ),
                )
            )
        else:
            expanded_targets.add(tgt)

    all_generated_targets = await MultiGet(parametrizations_gets)
    expanded_targets.update(
        tgt
        for generator, parametrizations in zip(generator_targets, all_generated_targets)
        for tgt in parametrizations.generated_or_generator(generator.address)
    )
    return Targets(expanded_targets)


@rule(desc="Find all targets in the project", level=LogLevel.DEBUG)
async def find_all_targets(_: AllTargetsRequest) -> AllTargets:
    tgts = await Get(
        Targets,
        RawSpecsWithoutFileOwners(
            recursive_globs=(RecursiveGlobSpec(""),), description_of_origin="the `AllTargets` rule"
        ),
    )
    return AllTargets(tgts)


@rule(desc="Find all targets in the project", level=LogLevel.DEBUG)
async def find_all_unexpanded_targets(_: AllTargetsRequest) -> AllUnexpandedTargets:
    tgts = await Get(
        UnexpandedTargets,
        RawSpecsWithoutFileOwners(
            recursive_globs=(RecursiveGlobSpec(""),), description_of_origin="the `AllTargets` rule"
        ),
    )
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


@rule(desc="Resolve transitive targets", level=LogLevel.DEBUG)
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
def coarsened_targets_request(addresses: Addresses) -> CoarsenedTargetsRequest:
    return CoarsenedTargetsRequest(addresses)


@rule(desc="Resolve coarsened targets", level=LogLevel.DEBUG)
async def coarsened_targets(request: CoarsenedTargetsRequest) -> CoarsenedTargets:
    dependency_mapping = await Get(
        _DependencyMapping,
        _DependencyMappingRequest(
            TransitiveTargetsRequest(
                request.roots, include_special_cased_deps=request.include_special_cased_deps
            ),
            expanded_targets=request.expanded_targets,
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
    root_addresses_set = set(request.roots)
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
        f"\n\nYou may want to run `{bin_name()} tailor` to autogenerate your BUILD files. See "
        f"{doc_url('create-initial-build-files')}.{option_msg}"
    )

    if owners_not_found_behavior == OwnersNotFoundBehavior.warn:
        logger.warning(msg)
    else:
        raise ResolveError(msg)


@dataclass(frozen=True)
class OwnersRequest:
    """A request for the owners of a set of file paths."""

    sources: tuple[str, ...]
    owners_not_found_behavior: OwnersNotFoundBehavior = OwnersNotFoundBehavior.ignore
    filter_by_global_options: bool = False


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

    def create_live_and_deleted_gets(
        *, filter_by_global_options: bool
    ) -> tuple[
        Get[FilteredTargets | Targets, RawSpecsWithoutFileOwners],
        Get[UnexpandedTargets, RawSpecsWithoutFileOwners],
    ]:
        """Walk up the buildroot looking for targets that would conceivably claim changed sources.

        For live files, we use Targets, which causes generated targets to be used rather than their
        target generators. For deleted files we use UnexpandedTargets, which have the original
        declared `sources` globs from target generators.

        We ignore unrecognized files, which can happen e.g. when finding owners for deleted files.
        """
        live_raw_specs = RawSpecsWithoutFileOwners(
            ancestor_globs=tuple(AncestorGlobSpec(directory=d) for d in live_dirs),
            filter_by_global_options=filter_by_global_options,
            description_of_origin="<owners rule - unused>",
            unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
        )
        live_get: Get[FilteredTargets | Targets, RawSpecsWithoutFileOwners] = (
            Get(FilteredTargets, RawSpecsWithoutFileOwners, live_raw_specs)
            if filter_by_global_options
            else Get(Targets, RawSpecsWithoutFileOwners, live_raw_specs)
        )
        deleted_get = Get(
            UnexpandedTargets,
            RawSpecsWithoutFileOwners(
                ancestor_globs=tuple(AncestorGlobSpec(directory=d) for d in deleted_dirs),
                filter_by_global_options=filter_by_global_options,
                description_of_origin="<owners rule - unused>",
                unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
            ),
        )
        return live_get, deleted_get

    live_get, deleted_get = create_live_and_deleted_gets(
        filter_by_global_options=owners_request.filter_by_global_options
    )
    live_candidate_tgts, deleted_candidate_tgts = await MultiGet(live_get, deleted_get)

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
            Get(
                BuildFileAddress,
                BuildFileAddressRequest(
                    tgt.address, description_of_origin="<owners rule - cannot trigger>"
                ),
            )
            for tgt in candidate_tgts
        )

        for candidate_tgt, bfa in zip(candidate_tgts, build_file_addresses):
            matching_files = set(
                candidate_tgt.get(SourcesField).filespec_matcher.matches(list(sources_set))
            )
            # Also consider secondary ownership, meaning it's not a `SourcesField` field with
            # primary ownership, but the target still should match the file. We can't use
            # `tgt.get()` because this is a mixin, and there technically may be >1 field.
            secondary_owner_fields = tuple(
                field
                for field in candidate_tgt.field_values.values()
                if isinstance(field, SecondaryOwnerMixin)
            )
            for secondary_owner_field in secondary_owner_fields:
                matching_files.update(
                    *secondary_owner_field.filespec_matcher.matches(list(sources_set))
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
# Resolve SourcesField
# -----------------------------------------------------------------------------------------------


@rule
def extract_unmatched_build_file_globs(
    global_options: GlobalOptions,
) -> UnmatchedBuildFileGlobs:
    return cast(
        UnmatchedBuildFileGlobs,
        resolve_conflicting_options(
            old_option="files_not_found_behavior",
            new_option="unmatched_build_file_globs",
            old_scope=global_options.options_scope,
            new_scope=global_options.options_scope,
            old_container=global_options.options,
            new_container=global_options.options,
        ),
    )


class AmbiguousCodegenImplementationsException(Exception):
    """Exception for when there are multiple codegen implementations and it is ambiguous which to
    use."""

    @classmethod
    def create(
        cls,
        generators: Iterable[type[GenerateSourcesRequest]],
        *,
        for_sources_types: Iterable[type[SourcesField]],
    ) -> AmbiguousCodegenImplementationsException:
        all_same_generator_paths = (
            len({(generator.input, generator.output) for generator in generators}) == 1
        )
        example_generator = list(generators)[0]
        input = example_generator.input.__name__
        if all_same_generator_paths:
            output = example_generator.output.__name__
            return cls(
                f"Multiple registered code generators can generate {output} from {input}. "
                "It is ambiguous which implementation to use.\n\nPossible implementations:\n\n"
                f"{bullet_list(sorted(generator.__name__ for generator in generators))}"
            )
        possible_output_types = sorted(
            generator.output.__name__
            for generator in generators
            if issubclass(generator.output, tuple(for_sources_types))
        )
        possible_generators_with_output = [
            f"{generator.__name__} -> {generator.output.__name__}"
            for generator in sorted(generators, key=lambda generator: generator.output.__name__)
        ]
        return cls(
            f"Multiple registered code generators can generate one of "
            f"{possible_output_types} from {input}. It is ambiguous which implementation to "
            f"use. This can happen when the call site requests too many different output types "
            f"from the same original protocol sources.\n\nPossible implementations with their "
            f"output type:\n\n"
            f"{bullet_list(possible_generators_with_output)}"
        )


@rule(desc="Hydrate the `sources` field")
async def hydrate_sources(
    request: HydrateSourcesRequest,
    unmatched_build_file_globs: UnmatchedBuildFileGlobs,
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
        raise AmbiguousCodegenImplementationsException.create(
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
    path_globs = sources_field.path_globs(unmatched_build_file_globs)
    snapshot = await Get(Snapshot, PathGlobs, path_globs)
    sources_field.validate_resolved_files(snapshot.files)

    # Finally, return if codegen is not in use; otherwise, run the relevant code generator.
    if not request.enable_codegen or generate_request_type is None:
        return HydratedSources(snapshot, sources_field.filespec, sources_type=sources_type)
    wrapped_protocol_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            sources_field.address,
            # It's only possible to hydrate sources on a target that we already know exists.
            description_of_origin="<infallible>",
        ),
    )
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
    request: SourcesPathsRequest, unmatched_build_file_globs: UnmatchedBuildFileGlobs
) -> SourcesPaths:
    sources_field = request.field
    path_globs = sources_field.path_globs(unmatched_build_file_globs)
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
    return SubprojectRoots(global_options.subproject_roots)


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
        description_of_origin=(
            f"the `{request.field.alias}` field from the target {request.field.address}"
        ),
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


@rule_helper
async def _fill_parameters(
    field_alias: str,
    consumer_tgt: Target,
    addresses: Iterable[Address],
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    field_defaults: FieldDefaults,
) -> tuple[Address, ...]:
    assert not isinstance(addresses, Iterator)

    parametrizations = await MultiGet(
        Get(
            _TargetParametrizations,
            _TargetParametrizationsRequest(
                address.maybe_convert_to_target_generator(),
                description_of_origin=f"the `{field_alias}` field of the target {consumer_tgt.address}",
            ),
        )
        for address in addresses
    )

    return tuple(
        parametrizations.get_subset(
            address, consumer_tgt, field_defaults, target_types_to_generate_requests
        ).address
        for address, parametrizations in zip(addresses, parametrizations)
    )


@rule(desc="Resolve direct dependencies")
async def resolve_dependencies(
    request: DependenciesRequest,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    union_membership: UnionMembership,
    subproject_roots: SubprojectRoots,
    field_defaults: FieldDefaults,
) -> Addresses:
    wrapped_tgt, explicitly_provided = await MultiGet(
        Get(
            WrappedTarget,
            # It's only possible to find dependencies for a target that we already know exists.
            WrappedTargetRequest(request.field.address, description_of_origin="<infallible>"),
        ),
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

    # If it's a target generator, inject dependencies on all of its generated targets.
    generated_addresses: tuple[Address, ...] = ()
    if target_types_to_generate_requests.is_generator(tgt) and not tgt.address.is_generated_target:
        parametrizations = await Get(
            _TargetParametrizations,
            _TargetParametrizationsRequest(
                tgt.address.maybe_convert_to_target_generator(),
                description_of_origin=(
                    f"the target generator {tgt.address.maybe_convert_to_target_generator()}"
                ),
            ),
        )
        generated_addresses = tuple(parametrizations.generated_for(tgt.address).keys())

    # See whether any explicitly provided dependencies are parametrized, but with partial/no
    # parameters. If so, fill them in.
    explicitly_provided_includes: Iterable[Address] = explicitly_provided.includes
    if explicitly_provided_includes:
        explicitly_provided_includes = await _fill_parameters(
            request.field.alias,
            tgt,
            explicitly_provided_includes,
            target_types_to_generate_requests,
            field_defaults,
        )
    explicitly_provided_ignores: FrozenOrderedSet[Address] = explicitly_provided.ignores
    if explicitly_provided_ignores:
        explicitly_provided_ignores = FrozenOrderedSet(
            await _fill_parameters(
                request.field.alias,
                tgt,
                tuple(explicitly_provided_ignores),
                target_types_to_generate_requests,
                field_defaults,
            )
        )

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
                    description_of_origin=(
                        f"the `{special_cased_field.alias}` field from the target {tgt.address}"
                    ),
                ),
            )
            for special_cased_field in special_cased_fields
            for addr in special_cased_field.to_unparsed_address_inputs().values
        )

    result = Addresses(
        sorted(
            {
                addr
                for addr in (
                    *generated_addresses,
                    *explicitly_provided_includes,
                    *itertools.chain.from_iterable(injected),
                    *itertools.chain.from_iterable(inferred),
                    *special_cased,
                )
                if addr not in explicitly_provided_ignores
            }
        )
    )

    # Validate dependencies.
    _ = await MultiGet(
        Get(
            ValidatedDependencies,
            ValidateDependenciesRequest,
            vd_request_type(vd_request_type.field_set_type.create(tgt), result),  # type: ignore[misc]
        )
        for vd_request_type in union_membership.get(ValidateDependenciesRequest)
        if vd_request_type.field_set_type.is_applicable(tgt)  # type: ignore[misc]
    )

    return result


@rule(desc="Resolve addresses")
async def resolve_unparsed_address_inputs(
    request: UnparsedAddressInputs, subproject_roots: SubprojectRoots
) -> Addresses:
    address_inputs = []
    invalid_addresses = []
    for v in request.values:
        try:
            address_inputs.append(
                AddressInput.parse(
                    v,
                    relative_to=request.relative_to,
                    subproject_roots=subproject_roots,
                    description_of_origin=request.description_of_origin,
                )
            )
        except AddressParseException:
            if not request.skip_invalid_addresses:
                raise
            invalid_addresses.append(v)

    if request.skip_invalid_addresses:
        maybe_addresses = await MultiGet(
            Get(MaybeAddress, AddressInput, ai) for ai in address_inputs
        )
        valid_addresses = []
        for maybe_address, address_input in zip(maybe_addresses, address_inputs):
            if isinstance(maybe_address.val, Address):
                valid_addresses.append(maybe_address.val)
            else:
                invalid_addresses.append(address_input.spec)

        if invalid_addresses:
            logger.debug(
                softwrap(
                    f"""
                    Invalid addresses from {request.description_of_origin}:
                    {sorted(invalid_addresses)}. Skipping them.
                    """
                )
            )
        return Addresses(valid_addresses)

    addresses = await MultiGet(Get(Address, AddressInput, ai) for ai in address_inputs)
    # Validate that the addresses exist. We do this eagerly here because
    # `Addresses -> UnexpandedTargets` does not preserve the `description_of_origin`, so it would
    # be too late, per https://github.com/pantsbuild/pants/issues/15858.
    await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(addr, description_of_origin=request.description_of_origin),
        )
        for addr in addresses
    )
    return Addresses(addresses)


# -----------------------------------------------------------------------------------------------
# Dynamic Field defaults
# -----------------------------------------------------------------------------------------------


@rule
async def field_defaults(union_membership: UnionMembership) -> FieldDefaults:
    requests = list(union_membership.get(FieldDefaultFactoryRequest))
    factories = await MultiGet(
        Get(FieldDefaultFactoryResult, FieldDefaultFactoryRequest, impl()) for impl in requests
    )
    return FieldDefaults(
        FrozenDict(
            (request.field_type, factory.default_factory)
            for request, factory in zip(requests, factories)
        )
    )


# -----------------------------------------------------------------------------------------------
# Find applicable field sets
# -----------------------------------------------------------------------------------------------


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


class GenerateFileTargets(GenerateTargetsRequest):
    generate_from = TargetFilesGenerator


@rule
async def generate_file_targets(
    request: GenerateFileTargets,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[MultipleSourcesField])
    )

    add_dependencies_on_all_siblings = False
    if request.generator.settings_request_cls:
        generator_settings = await Get(
            TargetFilesGeneratorSettings,
            TargetFilesGeneratorSettingsRequest,
            request.generator.settings_request_cls(),
        )
        add_dependencies_on_all_siblings = generator_settings.add_dependencies_on_all_siblings

    return _generate_file_level_targets(
        type(request.generator).generated_target_cls,
        request.generator,
        sources_paths.files,
        request.template_address,
        request.template,
        request.overrides,
        union_membership,
        add_dependencies_on_all_siblings=add_dependencies_on_all_siblings,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFileTargets),
    ]
