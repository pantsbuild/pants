# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from pants.backend.python.frameworks.stevedore.target_types import (
    AllStevedoreExtensionTargets,
    StevedoreEntryPointsField,
    StevedoreNamespaceField,
    StevedoreNamespacesField,
)
from pants.backend.python.target_types import (
    PythonDistributionDependenciesField,
    PythonTestsDependenciesField,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.base.specs import DirGlobSpec, RawSpecs
from pants.engine.addresses import Address
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    Target,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet

# -----------------------------------------------------------------------------------------------
# Utility rules to analyze all `StevedoreExtension` targets
# -----------------------------------------------------------------------------------------------


@rule(desc="Find all StevedoreExtension targets in project", level=LogLevel.DEBUG)
def find_all_stevedore_extension_targets(
    targets: AllTargets,
) -> AllStevedoreExtensionTargets:
    return AllStevedoreExtensionTargets(
        tgt for tgt in targets if tgt.has_field(StevedoreEntryPointsField)
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
    for extension in stevedore_extensions:
        mapping[str(extension[StevedoreNamespaceField].value)].append(extension)
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
    desc="Infer stevedore_extension target dependencies based on namespace list.",
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

    result: OrderedSet[Address] = OrderedSet(addresses)
    return InferredDependencies(sorted(result))


# -----------------------------------------------------------------------------------------------
# Dependencies for `python_distribution` targets
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonDistributionStevedoreNamespaceInferenceFieldSet(FieldSet):
    required_fields = (PythonDistributionDependenciesField,)


class InferSiblingStevedoreExtensionDependencies(InferDependenciesRequest):
    infer_from = PythonDistributionStevedoreNamespaceInferenceFieldSet


@rule(
    desc="Infer sibling stevedore_extension target dependencies for python_distributions.",
    level=LogLevel.DEBUG,
)
async def infer_sibling_stevedore_extension_dependencies(
    request: InferSiblingStevedoreExtensionDependencies,
) -> InferredDependencies:
    sibling_targets = await Get(
        Targets,
        RawSpecs(
            dir_globs=(DirGlobSpec(request.field_set.address.spec_path),),
            description_of_origin="infer_sibling_stevedore_extension_dependencies",
        ),
    )
    stevedore_targets: list[Target] = [
        tgt for tgt in sibling_targets if tgt.has_field(StevedoreEntryPointsField)
    ]

    if not stevedore_targets:
        return InferredDependencies(())

    addresses = [extension_tgt.address for extension_tgt in stevedore_targets]
    result: OrderedSet[Address] = OrderedSet(addresses)
    return InferredDependencies(sorted(result))


def rules():
    return [
        *collect_rules(),
        PythonTestsGeneratorTarget.register_plugin_field(StevedoreNamespacesField),
        PythonTestTarget.register_plugin_field(StevedoreNamespacesField),
        UnionRule(InferDependenciesRequest, InferStevedoreNamespaceDependencies),
        UnionRule(InferDependenciesRequest, InferSiblingStevedoreExtensionDependencies),
    ]
