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
    PythonDistribution,
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
    predicate: Callable[[PythonDistribution, str, str], bool]


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
        # use .val instead of .explicit_modules and .pex_binary_addresses to facilitate filtering
        for ep_group, entry_points in distribution_entry_points.val.items():
            for ep_name, ep_val in entry_points.items():
                if request.predicate(tgt, ep_group, ep_name):
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


def rules():
    return [
        *collect_rules(),
    ]
