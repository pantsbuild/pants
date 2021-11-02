# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Set

from pants.backend.java.dependency_inference.jvm_artifact_mappings import JVM_ARTIFACT_MAPPINGS
from pants.backend.java.subsystems.java_infer import JavaInferSubsystem
from pants.build_graph.address import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.jvm.target_types import JvmArtifactArtifactField, JvmArtifactGroupField
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet


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
    """Maps JVM artifact coordinates (with only group and artifact set) to the `Address` of each
    target specifying that coordinate."""

    artifacts: FrozenDict[UnversionedCoordinate, FrozenOrderedSet[Address]]

    def addresses_for_coordinates(
        self, coordinates: Iterable[UnversionedCoordinate]
    ) -> FrozenOrderedSet[Address]:
        candidate_artifact_addresses: Set[Address] = set()
        for coordinate in coordinates:
            candidates = self.artifacts.get(coordinate, FrozenOrderedSet())
            candidate_artifact_addresses.update(candidates)
        return FrozenOrderedSet(candidate_artifact_addresses)


class MutableTrieNode:
    def __init__(self):
        self.children: dict[str, MutableTrieNode] = {}
        self.recursive: bool = False
        self.coordinates: set[UnversionedCoordinate] = set()

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
        self._coordinates: FrozenOrderedSet[UnversionedCoordinate] = FrozenOrderedSet(
            node.coordinates
        )

    def find_child(self, name: str) -> FrozenTrieNode | None:
        return self._children.get(name)

    @property
    def recursive(self) -> bool:
        return self._recursive

    @property
    def coordinates(self) -> FrozenOrderedSet[UnversionedCoordinate]:
        return self._coordinates

    def __hash__(self) -> int:
        return hash((self._children, self._recursive, self._coordinates))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, FrozenTrieNode):
            return False
        return (
            self._children == other._children
            and self.recursive == other.recursive
            and self.coordinates == other.coordinates
        )

    def __repr__(self):
        return f"FrozenTrieNode(children={repr(self._children)}, recursive={self._recursive}, coordinate={self._coordinates})"


class AllJvmArtifactTargets(Targets):
    pass


@rule(desc="Find all jvm_artifact targets in project", level=LogLevel.DEBUG)
def find_all_jvm_artifact_targets(targets: AllTargets) -> AllJvmArtifactTargets:
    return AllJvmArtifactTargets(
        tgt for tgt in targets if tgt.has_fields((JvmArtifactGroupField, JvmArtifactArtifactField))
    )


@dataclass(frozen=True)
class ThirdPartyJavaPackageToArtifactMapping:
    mapping_root: FrozenTrieNode


@rule
async def find_available_third_party_artifacts(
    all_jvm_artifact_tgts: AllJvmArtifactTargets,
) -> AvailableThirdPartyArtifacts:
    artifact_mapping: dict[UnversionedCoordinate, set[Address]] = defaultdict(set)
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

        key = UnversionedCoordinate(group=group, artifact=artifact)
        artifact_mapping[key].add(tgt.address)

    return AvailableThirdPartyArtifacts(
        FrozenDict({key: FrozenOrderedSet(value) for key, value in artifact_mapping.items()})
    )


@rule
async def compute_java_third_party_artifact_mapping(
    java_infer_subsystem: JavaInferSubsystem,
) -> ThirdPartyJavaPackageToArtifactMapping:
    def insert(mapping: MutableTrieNode, imp: str, coordinate: UnversionedCoordinate) -> None:
        imp_parts = imp.split(".")
        recursive = False
        if imp_parts[-1] == "**":
            recursive = True
            imp_parts = imp_parts[0:-1]

        current_node = mapping
        for imp_part in imp_parts:
            child_node = current_node.ensure_child(imp_part)
            current_node = child_node

        current_node.coordinates.add(coordinate)
        current_node.recursive = recursive

    mapping = MutableTrieNode()
    for imp_name, imp_action in {
        **JVM_ARTIFACT_MAPPINGS,
        **java_infer_subsystem.third_party_import_mapping,
    }.items():
        value = UnversionedCoordinate.from_coord_str(imp_action)
        insert(mapping, imp_name, value)

    return ThirdPartyJavaPackageToArtifactMapping(FrozenTrieNode(mapping))


def find_artifact_mapping(
    import_name: str,
    mapping: ThirdPartyJavaPackageToArtifactMapping,
    available_artifacts: AvailableThirdPartyArtifacts,
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
        addresses = available_artifacts.addresses_for_coordinates(found_nodes[-1].coordinates)
        return addresses

    # Otherwise, check for the first found node (in reverse order) to match recursively, and use its coordinate.
    for found_node in reversed(found_nodes):
        if found_node.recursive:
            addresses = available_artifacts.addresses_for_coordinates(found_node.coordinates)
            return addresses

    # Nothing matched so return no match.
    return FrozenOrderedSet()


def rules():
    return collect_rules()
