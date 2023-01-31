# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from pants.backend.python.framework.stevedore.target_types import (
    AllStevedoreExtensionTargets,
    StevedoreNamespace,
    StevedoreNamespacesField,
)
from pants.backend.python.target_types import (
    PythonDistributionEntryPointsField,
    PythonTestsDependenciesField,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    AllTargets,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    Target,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet

# -----------------------------------------------------------------------------------------------
# Utility rules to analyze all StevedoreNamespace entry_points
# -----------------------------------------------------------------------------------------------


@rule(desc="Find all StevedoreExtension targets in project", level=LogLevel.DEBUG)
def find_all_python_distributions_with_stevedore_entry_points_targets(
    targets: AllTargets,
) -> AllStevedoreExtensionTargets:
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

    mapping: FrozenDict[str, tuple[Target, ...]]


@rule(
    desc="Creating map of stevedore_extension namespaces to StevedoreExtension targets",
    level=LogLevel.DEBUG,
)
async def map_stevedore_extensions(
    stevedore_extensions: AllStevedoreExtensionTargets,
) -> StevedoreExtensions:
    mapping: Mapping[str, list[Target]] = defaultdict(list)
    for tgt in stevedore_extensions:
        # namespace aka category aka group
        for namespace, entry_points in (
            tgt[PythonDistributionEntryPointsField].value or {}
        ).items():
            if isinstance(namespace, StevedoreNamespace):
                mapping[str(namespace)].append(tgt)
    return StevedoreExtensions(FrozenDict((k, tuple(v)) for k, v in sorted(mapping.items())))


# -----------------------------------------------------------------------------------------------
# Dependencies for `python_test` and `python_tests` targets
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonTestsStevedoreNamespaceInferenceFieldSet(FieldSet):
    required_fields = (PythonTestsDependenciesField, StevedoreNamespacesField)

    stevedore_namespaces: StevedoreNamespacesField


class InferStevedoreNamespaceDependencies(InferDependenciesRequest):
    infer_from = PythonTestsStevedoreNamespaceInferenceFieldSet


@rule(
    desc="Infer python_distribution target dependencies based on namespace list.",
    level=LogLevel.DEBUG,
)
async def infer_stevedore_namespace_dependencies(
    request: InferStevedoreNamespaceDependencies,
    stevedore_extensions: StevedoreExtensions,
) -> InferredDependencies:
    namespaces: StevedoreNamespacesField = request.field_set.stevedore_namespaces
    if namespaces.value is None:
        return InferredDependencies(())

    addresses: list[Address] = []
    for namespace in namespaces.value:
        extensions = stevedore_extensions.mapping.get(namespace, ())
        addresses.extend(extension.address for extension in extensions)

    # TODO: this infers deps on the python_distribution, but it should only infer deps
    #       on the entry_points for the requested namespaces, not all of them.
    result: OrderedSet[Address] = OrderedSet(addresses)
    return InferredDependencies(sorted(result))


def rules():
    return [
        *collect_rules(),
        PythonTestsGeneratorTarget.register_plugin_field(StevedoreNamespacesField),
        PythonTestTarget.register_plugin_field(StevedoreNamespacesField),
        UnionRule(InferDependenciesRequest, InferStevedoreNamespaceDependencies),
    ]
