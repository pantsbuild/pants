# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
)
from pants.backend.python.framework.stevedore.target_types import (
    AllStevedoreExtensionTargets,
    StevedoreExtensionTargets,
    StevedoreNamespace,
    StevedoreNamespacesField,
    StevedoreNamespacesProviderTargetsRequest,
)
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonDistributionDependenciesField,
    PythonDistributionEntryPointsField,
    PythonTestsDependenciesField,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    ResolvedPythonDistributionEntryPoints,
    ResolvePythonDistributionEntryPointsRequest,
)
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    Target,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap

# -----------------------------------------------------------------------------------------------
# Utility rules to analyze all StevedoreNamespace entry_points
# -----------------------------------------------------------------------------------------------


@rule(
    desc=f"Find all `{PythonDistribution.alias}` targets with `{StevedoreNamespace.alias}` entry_points",
    level=LogLevel.DEBUG,
)
def find_all_python_distributions_with_any_stevedore_entry_points(
    targets: AllTargets,
) -> AllStevedoreExtensionTargets:
    # This only supports specifying stevedore_namespace entry points in the
    # `entry_points` field of a `python_distribution`, not the `provides` field.
    # Use this: `python_distribution(entry_points={...})`
    # NOT this: `python_distribution(provides=python_artifact(entry_points={...}))`
    return AllStevedoreExtensionTargets(
        tgt
        for tgt in targets
        if tgt.has_field(PythonDistributionEntryPointsField)
        and any(
            # namespace aka category aka group
            isinstance(namespace, StevedoreNamespace)
            for namespace in (tgt[PythonDistributionEntryPointsField].value or {}).keys()
        )
    )


@dataclass(frozen=True)
class StevedoreExtensions:
    """A mapping of stevedore namespaces to a list of targets that provide them.

    Effectively, the targets are StevedoreExtension targets.
    """

    mapping: FrozenDict[StevedoreNamespace, tuple[Target, ...]]


@rule(
    desc=f"Create map of `{StevedoreNamespace.alias}` to `{PythonDistribution.alias}` targets",
    level=LogLevel.DEBUG,
)
async def map_stevedore_extensions(
    stevedore_extensions: AllStevedoreExtensionTargets,
) -> StevedoreExtensions:
    mapping: Mapping[StevedoreNamespace, list[Target]] = defaultdict(list)
    for tgt in stevedore_extensions:
        # namespace aka category aka group
        for namespace in (tgt[PythonDistributionEntryPointsField].value or {}).keys():
            if isinstance(namespace, StevedoreNamespace):
                mapping[namespace].append(tgt)
    return StevedoreExtensions(FrozenDict((k, tuple(v)) for k, v in sorted(mapping.items())))


@rule(
    desc=f"Find `{PythonDistribution.alias}` targets with entry_points in selected `{StevedoreNamespace.alias}`s",
    level=LogLevel.DEBUG,
)
def find_python_distributions_with_entry_points_in_stevedore_namespaces(
    request: StevedoreNamespacesProviderTargetsRequest,
    stevedore_extensions: StevedoreExtensions,
) -> StevedoreExtensionTargets:
    namespaces: StevedoreNamespacesField = request.stevedore_namespaces
    if namespaces.value is None:
        return StevedoreExtensionTargets(())

    return StevedoreExtensionTargets(
        {
            tgt
            for namespace in namespaces.value
            for tgt in stevedore_extensions.mapping.get(StevedoreNamespace(namespace), ())
        }
    )


# -----------------------------------------------------------------------------------------------
# Dependencies for `python_test` and `python_tests` targets
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonTestsStevedoreNamespaceInferenceFieldSet(FieldSet):
    required_fields = (PythonTestsDependenciesField, StevedoreNamespacesField)

    stevedore_namespaces: StevedoreNamespacesField


class InferStevedoreNamespacesDependencies(InferDependenciesRequest):
    infer_from = PythonTestsStevedoreNamespaceInferenceFieldSet


@rule(
    desc=f"Infer dependencies based on `{StevedoreNamespacesField.alias}` field.",
    level=LogLevel.DEBUG,
)
async def infer_stevedore_namespaces_dependencies(
    request: InferStevedoreNamespacesDependencies,
) -> InferredDependencies:
    requested_namespaces: StevedoreNamespacesField = request.field_set.stevedore_namespaces
    if requested_namespaces.value is None:
        return InferredDependencies(())

    targets = await Get(
        StevedoreExtensionTargets,
        StevedoreNamespacesProviderTargetsRequest(requested_namespaces),
    )

    # This is based on pants.backend.python.target_type_rules.infer_python_distribution_dependencies,
    # but handles multiple targets and filters the entry_points to just get the requested deps.
    all_explicit_dependencies = await MultiGet(
        Get(
            ExplicitlyProvidedDependencies,
            DependenciesRequest(tgt[PythonDistributionDependenciesField]),
        )
        for tgt in targets
    )
    all_resolved_entry_points = await MultiGet(
        Get(
            ResolvedPythonDistributionEntryPoints,
            ResolvePythonDistributionEntryPointsRequest(tgt[PythonDistributionEntryPointsField]),
        )
        for tgt in targets
    )

    all_module_entry_points = [
        (tgt.address, namespace, name, entry_point, explicitly_provided_deps)
        for tgt, distribution_entry_points, explicitly_provided_deps in zip(
            targets, all_resolved_entry_points, all_explicit_dependencies
        )
        for namespace, entry_points in distribution_entry_points.explicit_modules.items()
        for name, entry_point in entry_points.items()
    ]
    all_module_owners = await MultiGet(
        Get(PythonModuleOwners, PythonModuleOwnersRequest(entry_point.module, resolve=None))
        for _, _, _, entry_point, _ in all_module_entry_points
    )
    module_owners: OrderedSet[Address] = OrderedSet()
    for (address, namespace, name, entry_point, explicitly_provided_deps), owners in zip(
        all_module_entry_points, all_module_owners
    ):
        if namespace not in requested_namespaces.value:
            continue

        field_str = repr({namespace: {name: entry_point.spec}})
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
        module_owners.update(unambiguous_owners)

    result: tuple[Address, ...] = Addresses(module_owners)
    for distribution_entry_points in all_resolved_entry_points:
        result += distribution_entry_points.pex_binary_addresses
    return InferredDependencies(result)


def rules():
    return [
        *collect_rules(),
        PythonTestsGeneratorTarget.register_plugin_field(StevedoreNamespacesField),
        PythonTestTarget.register_plugin_field(StevedoreNamespacesField),
        UnionRule(InferDependenciesRequest, InferStevedoreNamespacesDependencies),
    ]
