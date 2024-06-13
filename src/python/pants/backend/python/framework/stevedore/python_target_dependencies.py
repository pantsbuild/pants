# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from pants.backend.python.framework.stevedore.target_types import (
    AllStevedoreExtensionTargets,
    StevedoreExtensionTargets,
    StevedoreNamespace,
    StevedoreNamespacesField,
    StevedoreNamespacesProviderTargetsRequest,
)
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonDistributionEntryPointsField,
    PythonTestsDependenciesField,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.backend.python.util_rules import entry_points
from pants.backend.python.util_rules.entry_points import (
    EntryPointDependencies,
    GetEntryPointDependenciesRequest,
)
from pants.engine.rules import Get, collect_rules, rule
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
    return StevedoreExtensions(
        FrozenDict((k, tuple(sorted(v))) for k, v in sorted(mapping.items()))
    )


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

    requested_namespaces_value = requested_namespaces.value
    entry_point_dependencies = await Get(
        EntryPointDependencies,
        GetEntryPointDependenciesRequest(
            targets,
            lambda tgt, namespace, ep_name: namespace in requested_namespaces_value,
        ),
    )

    return InferredDependencies(entry_point_dependencies.addresses)


def rules():
    return [
        *collect_rules(),
        *entry_points.rules(),
        PythonTestsGeneratorTarget.register_plugin_field(StevedoreNamespacesField),
        PythonTestTarget.register_plugin_field(StevedoreNamespacesField),
        UnionRule(InferDependenciesRequest, InferStevedoreNamespacesDependencies),
    ]
