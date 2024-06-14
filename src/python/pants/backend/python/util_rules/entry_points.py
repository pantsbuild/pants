# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Callable, Iterable

from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
)
from pants.backend.python.target_types import (
    EntryPoint,
    PythonDistributionDependenciesField,
    PythonDistributionEntryPointsField,
    PythonTestTarget,
    PythonTestsDependenciesField,
    PythonTestsEntryPointDependenciesField,
    PythonTestsGeneratorTarget,
    ResolvePythonDistributionEntryPointsRequest,
    ResolvedPythonDistributionEntryPoints,
)
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.internals.native_engine import Address
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import softwrap


PythonDistributionEntryPointGroupPredicate = Callable[
    [PythonDistributionEntryPointsField, str], bool
]
PythonDistributionEntryPointPredicate = Callable[
    [PythonDistributionEntryPointsField, str, str], bool
]


def get_python_distribution_entry_point_unambiguous_module_owners(
    address: Address,
    entry_point_group: str,  # group is the pypa term; aka category or namespace
    entry_point_name: str,
    entry_point: EntryPoint,
    explicitly_provided_deps: ExplicitlyProvidedDependencies,
    owners: PythonModuleOwners,
) -> tuple[Address]:
    field_str = repr({entry_point_group: {entry_point_name: entry_point.spec}})
    explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
        owners.ambiguous,
        address,
        import_reference="module",
        context=softwrap(
            f"""
            The python_distribution target {address} has the field
            `entry_points={field_str}`, which maps to the Python module
            `{entry_point.module}`
            """
        ),
    )
    maybe_disambiguated = explicitly_provided_deps.disambiguated(owners.ambiguous)
    unambiguous_owners = owners.unambiguous or (
        (maybe_disambiguated,) if maybe_disambiguated else ()
    )
    return unambiguous_owners


@dataclass(frozen=True)
class GetEntryPointDependenciesRequest:
    targets: Targets
    group_predicate: PythonDistributionEntryPointGroupPredicate
    predicate: PythonDistributionEntryPointPredicate


@dataclass(frozen=True)
class EntryPointDependencies:
    addresses: FrozenOrderedSet[Address]

    def __init__(self, addresses: Iterable[Address]) -> None:
        object.__setattr__(self, "addresses", FrozenOrderedSet(sorted(addresses)))


@rule
async def get_filtered_entry_point_dependencies(
    request: GetEntryPointDependenciesRequest,
) -> EntryPointDependencies:
    # This is based on pants.backend.python.target_type_rules.infer_python_distribution_dependencies,
    # but handles multiple targets and filters the entry_points to just get the requested deps.
    all_explicit_dependencies = await MultiGet(
        Get(
            ExplicitlyProvidedDependencies,
            DependenciesRequest(tgt[PythonDistributionDependenciesField]),
        )
        for _, tgt in request.targets
    )
    resolved_entry_points = await MultiGet(
        Get(
            ResolvedPythonDistributionEntryPoints,
            ResolvePythonDistributionEntryPointsRequest(tgt[PythonDistributionEntryPointsField]),
        )
        for _, tgt in request.targets
    )

    filtered_entry_point_pex_addresses: list[Address] = []
    filtered_entry_point_modules: list[
        tuple[Address, str, str, EntryPoint, ExplicitlyProvidedDependencies]
    ] = []

    distribution_entry_points: ResolvedPythonDistributionEntryPoints
    for tgt, distribution_entry_points, explicitly_provided_deps in zip(
        request.targets, resolved_entry_points, all_explicit_dependencies
    ):
        entry_points_field = tgt[PythonDistributionEntryPointsField]
        # use .val instead of .explicit_modules and .pex_binary_addresses to facilitate filtering
        for ep_group, entry_points in distribution_entry_points.val.items():
            want_group = request.group_predicate(entry_points_field, ep_group)
            if not want_group:
                continue
            for ep_name, ep_val in entry_points.items():
                if want_group or request.predicate(entry_points_field, ep_group, ep_name):
                    if ep_val.pex_binary_address:
                        filtered_entry_point_pex_addresses.append(ep_val.pex_binary_address)
                    else:
                        filtered_entry_point_modules.append(
                            (
                                tgt.address,
                                ep_group,
                                ep_name,
                                ep_val.entry_point,
                                explicitly_provided_deps,
                            )
                        )
    filtered_module_owners = await MultiGet(
        Get(PythonModuleOwners, PythonModuleOwnersRequest(entry_point.module, resolve=None))
        for _, _, _, entry_point, _ in filtered_entry_point_modules
    )

    filtered_unambiguous_module_owners: OrderedSet[Address] = OrderedSet()
    for (address, ep_group, ep_name, entry_point, explicitly_provided_deps), owners in zip(
        filtered_entry_point_modules, filtered_module_owners
    ):
        filtered_unambiguous_module_owners.update(
            get_python_distribution_entry_point_unambiguous_module_owners(
                address, ep_group, ep_name, entry_point, explicitly_provided_deps, owners
            )
        )

    return EntryPointDependencies(
        Addresses(*filtered_entry_point_pex_addresses, *filtered_unambiguous_module_owners)
    )


@dataclass(frozen=True)
class PythonTestsEntryPointDependenciesInferenceFieldSet(FieldSet):

    required_fields = (
        PythonTestsDependenciesField,
        PythonTestsEntryPointDependenciesField,
    )
    entry_point_dependencies: PythonTestsEntryPointDependenciesField


class InferEntryPointDependencies(InferDependenciesRequest):
    infer_from = PythonTestsEntryPointDependenciesField


@rule(
    desc=f"Infer dependencies based on `{PythonTestsEntryPointDependenciesField.alias}` field.",
    level=LogLevel.DEBUG,
)
async def infer_entry_point_dependencies(
    request: InferEntryPointDependencies,
) -> InferredDependencies:
    entry_point_deps: PythonTestsEntryPointDependenciesField = (
        request.field_set.entry_point_dependencies
    )
    if entry_point_deps.value is None:
        return InferredDependencies([])

    targets = await Get(
        Targets,
        UnparsedAddressInputs(
            entry_point_deps.value.keys(),
            owning_address=request.field_set.address,
            description_of_origin=f"{PythonTestsEntryPointDependenciesField.alias} from {request.field_set.address}",
        ),
    )

    requested_entry_points: dict[PythonDistributionEntryPointsField, set[str]] = {}
    wanted_targets = []

    address: Address
    requested_ep: tuple[str, ...]
    for target, (address, requested_ep) in zip(targets, entry_point_deps.value.items()):
        assert target.address == address, "sort order was not preserved"

        if not requested_ep:
            # requested an empty list, so no entry points were actually requested.
            continue
        if "*" in requested_ep and len(requested_ep) > 1:
            requested_ep = ("*",)

        if not target.has_field(PythonDistributionEntryPointsField):
            # unknown target type. ignore
            continue
        entry_points_field = target.get(PythonDistributionEntryPointsField)
        if not entry_points_field.value:
            # no entry points can be resolved.
            # TODO: Maybe warn that the requested entry points do not exist?
            continue
        wanted_targets.append(target)
        requested_entry_points[entry_points_field] = set(requested_ep)

    def group_predicate(field: PythonDistributionEntryPointsField, ep_group: str) -> bool:
        relevant = {"*", ep_group}
        requested = requested_entry_points[field]
        if relevant & requested:
            # at least one item in requested is relevant
            return True
        return False

    def predicate(field: PythonDistributionEntryPointsField, ep_group: str, ep_name: str) -> bool:
        requested = requested_entry_points[field]
        if f"{ep_group}/{ep_name}" in requested:
            return True
        return False

    entry_point_dependencies = await Get(
        EntryPointDependencies,
        GetEntryPointDependenciesRequest(Targets(wanted_targets), group_predicate, predicate),
    )
    return InferredDependencies(entry_point_dependencies.addresses)


def rules():
    return [
        *collect_rules(),
        PythonTestTarget.register_plugin_field(PythonTestsEntryPointDependenciesField),
        PythonTestsGeneratorTarget.register_plugin_field(
            PythonTestsEntryPointDependenciesField,
            as_moved_field=True,
        ),
        UnionRule(InferDependenciesRequest, InferEntryPointDependencies),
    ]
