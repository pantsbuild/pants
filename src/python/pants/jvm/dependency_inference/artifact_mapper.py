# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from pants.backend.java.subsystems.java_infer import JavaInferSubsystem
from pants.build_graph.address import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.jvm.dependency_inference.jvm_artifact_mappings import JVM_ARTIFACT_MAPPINGS
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactGroupField,
    JvmArtifactPackagesField,
)
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnversionedCoordinate:
    group: str
    artifact: str

    @classmethod
    def from_coord_str(cls, coord: str) -> UnversionedCoordinate:
        coordinate_parts = coord.split(":")
        if len(coordinate_parts) != 2:
            raise ValueError(f"Invalid coordinate specifier: {coord}")
        return UnversionedCoordinate(group=coordinate_parts[0], artifact=coordinate_parts[1])


@dataclass(frozen=True)
class AvailableThirdPartyArtifacts:
    """Maps JVM unversioned coordinates to target `Address`es and declared packages."""

    artifacts: FrozenDict[UnversionedCoordinate, tuple[tuple[Address, ...], tuple[str, ...]]]

    def addresses_for_coordinates(
        self, coordinates: Iterable[UnversionedCoordinate]
    ) -> OrderedSet[Address]:
        candidate_artifact_addresses: OrderedSet[Address] = OrderedSet()
        for coordinate in coordinates:
            candidates = self.artifacts.get(coordinate)
            if candidates:
                candidate_artifact_addresses.update(address for address in candidates[0])
        return candidate_artifact_addresses


class MutableTrieNode:
    def __init__(self):
        self.children: dict[str, MutableTrieNode] = {}
        self.recursive: bool = False
        self.addresses: OrderedSet[Address] = OrderedSet()

    def ensure_child(self, name: str) -> MutableTrieNode:
        if name in self.children:
            return self.children[name]
        node = MutableTrieNode()
        self.children[name] = node
        return node


@frozen_after_init
class FrozenTrieNode:
    def __init__(self, node: MutableTrieNode) -> None:
        children = {}
        for key, child in node.children.items():
            children[key] = FrozenTrieNode(child)
        self._children: FrozenDict[str, FrozenTrieNode] = FrozenDict(children)
        self._recursive: bool = node.recursive
        self._addresses: FrozenOrderedSet[Address] = FrozenOrderedSet(node.addresses)

    def find_child(self, name: str) -> FrozenTrieNode | None:
        return self._children.get(name)

    @property
    def recursive(self) -> bool:
        return self._recursive

    @property
    def addresses(self) -> FrozenOrderedSet[Address]:
        return self._addresses

    def __hash__(self) -> int:
        return hash((self._children, self._recursive, self._addresses))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, FrozenTrieNode):
            return False
        return (
            self._children == other._children
            and self.recursive == other.recursive
            and self.addresses == other.addresses
        )

    def __repr__(self):
        return f"FrozenTrieNode(children={repr(self._children)}, recursive={self._recursive}, addresses={self._addresses})"


class AllJvmArtifactTargets(Targets):
    pass


@rule(desc="Find all jvm_artifact targets in project", level=LogLevel.DEBUG)
def find_all_jvm_artifact_targets(targets: AllTargets) -> AllJvmArtifactTargets:
    return AllJvmArtifactTargets(
        tgt for tgt in targets if tgt.has_fields((JvmArtifactGroupField, JvmArtifactArtifactField))
    )


@dataclass(frozen=True)
class ThirdPartyPackageToArtifactMapping:
    mapping_root: FrozenTrieNode


@rule
async def find_available_third_party_artifacts(
    all_jvm_artifact_tgts: AllJvmArtifactTargets,
) -> AvailableThirdPartyArtifacts:
    address_mapping: dict[UnversionedCoordinate, OrderedSet[Address]] = defaultdict(OrderedSet)
    package_mapping: dict[UnversionedCoordinate, OrderedSet[str]] = defaultdict(OrderedSet)
    for tgt in all_jvm_artifact_tgts:
        group = tgt[JvmArtifactGroupField].value
        if not group:
            raise ValueError(
                f"The {JvmArtifactGroupField.alias} field of target {tgt.address} must be set."
            )

        artifact = tgt[JvmArtifactArtifactField].value
        if not artifact:
            raise ValueError(
                f"The {JvmArtifactArtifactField.alias} field of target {tgt.address} must be set."
            )
        packages: tuple[str, ...] = ()
        declared_packages = tgt[JvmArtifactPackagesField].value
        if declared_packages:
            packages = tuple(declared_packages)

        key = UnversionedCoordinate(group=group, artifact=artifact)
        address_mapping[key].add(tgt.address)
        package_mapping[key].update(packages)

    return AvailableThirdPartyArtifacts(
        FrozenDict(
            {
                key: (tuple(addresses), tuple(package_mapping[key]))
                for key, addresses in address_mapping.items()
            }
        )
    )


@rule
async def compute_java_third_party_artifact_mapping(
    java_infer_subsystem: JavaInferSubsystem,
    available_artifacts: AvailableThirdPartyArtifacts,
) -> ThirdPartyPackageToArtifactMapping:
    """Implements the mapping logic from the `jvm_artifact` and `java-infer` help."""

    def insert(
        mapping: MutableTrieNode, package_pattern: str, addresses: Iterable[Address]
    ) -> None:
        imp_parts = package_pattern.split(".")
        recursive = False
        if imp_parts[-1] == "**":
            recursive = True
            imp_parts = imp_parts[0:-1]

        current_node = mapping
        for imp_part in imp_parts:
            child_node = current_node.ensure_child(imp_part)
            current_node = child_node

        current_node.addresses.update(addresses)
        current_node.recursive = recursive

    # Build a default mapping from coord to package.
    # TODO: Consider inverting the definitions of these mappings.
    default_coords_to_packages: dict[UnversionedCoordinate, OrderedSet[str]] = defaultdict(
        OrderedSet
    )
    for package, unversioned_coord_str in {
        **JVM_ARTIFACT_MAPPINGS,
        **java_infer_subsystem.third_party_import_mapping,
    }.items():
        unversioned_coord = UnversionedCoordinate.from_coord_str(unversioned_coord_str)
        default_coords_to_packages[unversioned_coord].add(package)

    # Build the mapping from packages to addresses.
    mapping = MutableTrieNode()
    for coord, (addresses, packages) in available_artifacts.artifacts.items():
        if not packages:
            # If no packages were explicitly defined, fall back to our default mapping.
            packages = tuple(default_coords_to_packages[coord])
        if not packages:
            # Default to exposing the `group` name as a package.
            packages = (f"{coord.group}.**",)
        for package in packages:
            insert(mapping, package, addresses)

    return ThirdPartyPackageToArtifactMapping(FrozenTrieNode(mapping))


def find_artifact_mapping(
    import_name: str,
    mapping: ThirdPartyPackageToArtifactMapping,
) -> FrozenOrderedSet[Address]:
    imp_parts = import_name.split(".")
    current_node = mapping.mapping_root

    found_nodes = []
    for imp_part in imp_parts:
        child_node_opt = current_node.find_child(imp_part)
        if not child_node_opt:
            break
        found_nodes.append(child_node_opt)
        current_node = child_node_opt

    if not found_nodes:
        return FrozenOrderedSet()

    # If the length of the found nodes equals the number of parts of the package path, then there
    # is an exact match.
    if len(found_nodes) == len(imp_parts):
        return found_nodes[-1].addresses

    # Otherwise, check for the first found node (in reverse order) to match recursively, and use its coordinate.
    for found_node in reversed(found_nodes):
        if found_node.recursive:
            return found_node.addresses

    # Nothing matched so return no match.
    return FrozenOrderedSet()


def rules():
    return collect_rules()
