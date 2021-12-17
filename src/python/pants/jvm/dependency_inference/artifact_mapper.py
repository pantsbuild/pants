# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, DefaultDict, Iterable, Tuple

from pants.backend.java.subsystems.java_infer import JavaInferSubsystem
from pants.build_graph.address import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.jvm.dependency_inference.jvm_artifact_mappings import JVM_ARTIFACT_MAPPINGS
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactGroupField,
    JvmArtifactPackagesField,
    JvmProvidesTypesField,
)
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

_ResolveName = str


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


class AvailableThirdPartyArtifacts(
    FrozenDict[
        Tuple[_ResolveName, UnversionedCoordinate], Tuple[Tuple[Address, ...], Tuple[str, ...]]
    ]
):
    """Maps coordinates and resolve names to target `Address`es and declared packages."""


class MutableTrieNode:
    __slots__ = [
        "children",
        "recursive",
        "addresses",
        "first_party",
    ]  # don't use a `dict` to store attrs

    def __init__(self):
        self.children: dict[str, MutableTrieNode] = {}
        self.recursive: bool = False
        self.addresses: OrderedSet[Address] = OrderedSet()
        self.first_party: bool = False

    def ensure_child(self, name: str) -> MutableTrieNode:
        if name in self.children:
            return self.children[name]
        node = MutableTrieNode()
        self.children[name] = node
        return node


@frozen_after_init
class FrozenTrieNode:
    __slots__ = [
        "_is_frozen",
        "_children",
        "_recursive",
        "_addresses",
        "_first_party",
    ]  # don't use a `dict` to store attrs (speeds up attr access significantly)

    def __init__(self, node: MutableTrieNode) -> None:
        children = {}
        for key, child in node.children.items():
            children[key] = FrozenTrieNode(child)
        self._children: FrozenDict[str, FrozenTrieNode] = FrozenDict(children)
        self._recursive: bool = node.recursive
        self._addresses: FrozenOrderedSet[Address] = FrozenOrderedSet(node.addresses)
        self._first_party: bool = node.first_party

    def find_child(self, name: str) -> FrozenTrieNode | None:
        return self._children.get(name)

    @property
    def recursive(self) -> bool:
        return self._recursive

    @property
    def first_party(self) -> bool:
        return self._first_party

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
        return f"FrozenTrieNode(children={repr(self._children)}, recursive={self._recursive}, addresses={self._addresses}, first_party={self._first_party})"


class AllJvmArtifactTargets(Targets):
    pass


class AllJvmTypeProvidingTargets(Targets):
    pass


@rule(desc="Find all jvm_artifact targets in project", level=LogLevel.DEBUG)
def find_all_jvm_artifact_targets(targets: AllTargets) -> AllJvmArtifactTargets:
    return AllJvmArtifactTargets(
        tgt for tgt in targets if tgt.has_fields((JvmArtifactGroupField, JvmArtifactArtifactField))
    )


@rule(desc="Find all targets with experimental_provides fields in project", level=LogLevel.DEBUG)
def find_all_jvm_provides_fields(targets: AllTargets) -> AllJvmTypeProvidingTargets:
    return AllJvmTypeProvidingTargets(
        tgt
        for tgt in targets
        if tgt.has_field(JvmProvidesTypesField) and tgt[JvmProvidesTypesField].value is not None
    )


@dataclass(frozen=True)
class ThirdPartyPackageToArtifactMapping:
    mapping_roots: FrozenDict[_ResolveName, FrozenTrieNode]

    def addresses_for_symbol(
        self, symbol: str, resolves: Iterable[str]
    ) -> FrozenOrderedSet[Address]:
        def addresses_for_resolve(resolve: str) -> FrozenOrderedSet[Address]:
            imp_parts = symbol.split(".")

            # Note that it's possible to have a resolve with no associated artifacts.
            current_node = self.mapping_roots.get(resolve)
            if not current_node:
                return FrozenOrderedSet()

            found_nodes = []
            for imp_part in imp_parts:
                child_node_opt = current_node.find_child(imp_part)
                if not child_node_opt:
                    break
                found_nodes.append(child_node_opt)
                current_node = child_node_opt

            if not found_nodes:
                return FrozenOrderedSet()

            # If the length of the found nodes equals the number of parts of the package path, then
            # there is an exact match.
            if len(found_nodes) == len(imp_parts):
                best_match = found_nodes[-1]
                if best_match.first_party:
                    return (
                        FrozenOrderedSet()
                    )  # The first-party symbol mapper should provide this dep
                return found_nodes[-1].addresses

            # Otherwise, check for the first found node (in reverse order) to match recursively, and
            # use its coordinate.
            for found_node in reversed(found_nodes):
                if found_node.recursive:
                    return found_node.addresses

            # Nothing matched so return no match.
            return FrozenOrderedSet()

        return FrozenOrderedSet(
            itertools.chain.from_iterable(addresses_for_resolve(resolve) for resolve in resolves)
        )


@rule
async def find_available_third_party_artifacts(
    all_jvm_artifact_tgts: AllJvmArtifactTargets, jvm: JvmSubsystem
) -> AvailableThirdPartyArtifacts:
    address_mapping: DefaultDict[
        tuple[_ResolveName, UnversionedCoordinate], OrderedSet[Address]
    ] = defaultdict(OrderedSet)
    package_mapping: DefaultDict[
        tuple[_ResolveName, UnversionedCoordinate], OrderedSet[str]
    ] = defaultdict(OrderedSet)
    for tgt in all_jvm_artifact_tgts:
        coord = UnversionedCoordinate(
            group=tgt[JvmArtifactGroupField].value, artifact=tgt[JvmArtifactArtifactField].value
        )
        for resolve in jvm.resolves_for_target(tgt):
            key = (resolve, coord)
            address_mapping[key].add(tgt.address)
            package_mapping[key].update(tgt[JvmArtifactPackagesField].value or ())

    return AvailableThirdPartyArtifacts(
        {
            key: (tuple(addresses), tuple(package_mapping[key]))
            for key, addresses in address_mapping.items()
        }
    )


@rule
async def compute_java_third_party_artifact_mapping(
    java_infer_subsystem: JavaInferSubsystem,
    available_artifacts: AvailableThirdPartyArtifacts,
    all_jvm_type_providing_tgts: AllJvmTypeProvidingTargets,
) -> ThirdPartyPackageToArtifactMapping:
    """Implements the mapping logic from the `jvm_artifact` and `java-infer` help."""

    def insert(
        mapping: MutableTrieNode,
        package_pattern: str,
        addresses: Iterable[Address],
        first_party: bool,
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
        current_node.first_party = first_party
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

    # Build mappings per resolve from packages to addresses.
    mappings: DefaultDict[_ResolveName, MutableTrieNode] = defaultdict(MutableTrieNode)
    for (resolve_name, coord), (addresses, packages) in available_artifacts.items():
        if not packages:
            # If no packages were explicitly defined, fall back to our default mapping.
            packages = tuple(default_coords_to_packages[coord])
        if not packages:
            # Default to exposing the `group` name as a package.
            packages = (f"{coord.group}.**",)
        mapping = mappings[resolve_name]
        for package in packages:
            insert(mapping, package, addresses, first_party=False)

    # Mark types that have strong first-party declarations as first-party
    for tgt in all_jvm_type_providing_tgts:
        for provides_type in tgt[JvmProvidesTypesField].value or []:
            for mapping in mappings.values():
                insert(mapping, provides_type, [], first_party=True)

    return ThirdPartyPackageToArtifactMapping(
        FrozenDict(
            (resolve_name, FrozenTrieNode(mapping)) for resolve_name, mapping in mappings.items()
        )
    )


def rules():
    return collect_rules()
