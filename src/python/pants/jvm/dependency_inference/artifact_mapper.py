# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, DefaultDict, Iterable, Iterator, Tuple

from pants.backend.java.subsystems.java_infer import JavaInferSubsystem
from pants.build_graph.address import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.jvm.dependency_inference.jvm_artifact_mappings import JVM_ARTIFACT_MAPPINGS
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactGroupField,
    JvmArtifactPackagesField,
    JvmProvidesTypesField,
    JvmResolveField,
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


# A namespace for a symbol which defines the scope for name collisions and ambiguity. For example:
# if a JVM language allows the same symbol to be declared in an unambiguous way in multiple files
# (such as Scala `package objects` declaring a type alias for a class/object in another file) it
# can use a non-default namespace name of its choice.
SymbolNamespace = str


DEFAULT_SYMBOL_NAMESPACE: SymbolNamespace = "default"


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
        self.addresses: dict[SymbolNamespace, OrderedSet[Address]] = defaultdict(OrderedSet)
        self.first_party: bool = False

    def _ensure_child(self, name: str) -> MutableTrieNode:
        if name in self.children:
            return self.children[name]
        node = MutableTrieNode()
        self.children[name] = node
        return node

    def insert(
        self,
        symbol: str,
        addresses: Iterable[Address],
        *,
        first_party: bool,
        namespace: SymbolNamespace = DEFAULT_SYMBOL_NAMESPACE,
        recursive: bool = False,
    ) -> None:
        imp_parts = symbol.split(".")
        current_node = self
        for imp_part in imp_parts:
            child_node = current_node._ensure_child(imp_part)
            current_node = child_node

        current_node.addresses[namespace].update(addresses)
        current_node.first_party = first_party
        current_node.recursive = recursive

    def frozen(self) -> FrozenTrieNode:
        return FrozenTrieNode(self)


FrozenTrieNodeItem = Tuple[str, bool, FrozenDict[SymbolNamespace, FrozenOrderedSet[Address]], bool]


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
        self._addresses: FrozenDict[SymbolNamespace, FrozenOrderedSet[Address]] = FrozenDict(
            {ns: FrozenOrderedSet(addresses) for ns, addresses in node.addresses.items()}
        )
        self._first_party: bool = node.first_party

    def find_child(self, name: str) -> FrozenTrieNode | None:
        return self._children.get(name)

    @property
    def recursive(self) -> bool:
        return self._recursive

    @property
    def first_party(self) -> bool:
        return self._first_party

    def addresses_for_symbol(
        self, symbol: str
    ) -> FrozenDict[SymbolNamespace, FrozenOrderedSet[Address]]:
        current_node = self
        imp_parts = symbol.split(".")

        found_nodes = []
        for imp_part in imp_parts:
            child_node_opt = current_node.find_child(imp_part)
            if not child_node_opt:
                break
            found_nodes.append(child_node_opt)
            current_node = child_node_opt

        if not found_nodes:
            return FrozenDict()

        # If the length of the found nodes equals the number of parts of the package path, then
        # there is an exact match.
        if len(found_nodes) == len(imp_parts):
            return found_nodes[-1].addresses

        # Otherwise, check for the first found node (in reverse order) to match recursively, and
        # use its coordinate.
        for found_node in reversed(found_nodes):
            if found_node.recursive:
                return found_node.addresses

        # Nothing matched so return no match.
        return FrozenDict()

    @property
    def addresses(self) -> FrozenDict[SymbolNamespace, FrozenOrderedSet[Address]]:
        return self._addresses

    @classmethod
    def merge(cls, nodes: Iterable[FrozenTrieNode]) -> FrozenTrieNode:
        """Merges the given `FrozenTrieNode` instances.

        TODO: This is currently implemented as merging-from-scratch, but could be trie-aware.
        """
        result = MutableTrieNode()
        for node in nodes:
            for symbol, recursive, address_namespaces, first_party in node:
                for namespace, addresses in address_namespaces.items():
                    result.insert(
                        symbol,
                        addresses,
                        recursive=recursive,
                        first_party=first_party,
                        namespace=namespace,
                    )
        return FrozenTrieNode(result)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "children": {name: child.to_json_dict() for name, child in self._children.items()},
            **({"addresses": [str(a) for a in self._addresses]} if self._addresses else {}),
            "recursive": self._recursive,
            "first_party": self._first_party,
        }

    def _iter_helper(self, symbol: list[str]) -> Iterator[FrozenTrieNodeItem]:
        if symbol and self._addresses:
            yield (".".join(symbol), self._recursive, self._addresses, self._first_party)
        for name, child in self._children.items():
            symbol.append(name)
            yield from child._iter_helper(symbol)
            symbol.pop()

    def __iter__(self) -> Iterator[FrozenTrieNodeItem]:
        """Iterates through all nodes in the trie.

        TODO: This is primarily used in `FrozenTrieNode.merge`: if that method switches to
        trie-aware merging, this should likely be removed.
        """
        yield from self._iter_helper([])

    def __hash__(self) -> int:
        return hash((self._children, self._recursive, self._addresses))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, FrozenTrieNode):
            return False
        return (
            self.recursive == other.recursive
            and self.first_party == other.first_party
            and self.addresses == other.addresses
            and self._children == other._children
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


class ThirdPartySymbolMapping(FrozenDict[_ResolveName, FrozenTrieNode]):
    """The third party symbols provided by all `jvm_artifact` targets."""


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
        resolve = tgt[JvmResolveField].normalized_value(jvm)
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
async def compute_java_third_party_symbol_mapping(
    java_infer_subsystem: JavaInferSubsystem,
    available_artifacts: AvailableThirdPartyArtifacts,
    all_jvm_type_providing_tgts: AllJvmTypeProvidingTargets,
) -> ThirdPartySymbolMapping:
    """Implements the mapping logic from the `jvm_artifact` and `java-infer` help."""

    def symbol_from_package_pattern(package_pattern: str) -> tuple[str, bool]:
        wildcard_suffix = ".**"
        if package_pattern.endswith(wildcard_suffix):
            return package_pattern[: -len(wildcard_suffix)], True
        else:
            return package_pattern, False

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
            symbol, recursive = symbol_from_package_pattern(package)
            mapping.insert(symbol, addresses, first_party=False, recursive=recursive)

    # Mark types that have strong first-party declarations as first-party
    for tgt in all_jvm_type_providing_tgts:
        for provides_type in tgt[JvmProvidesTypesField].value or []:
            for mapping in mappings.values():
                mapping.insert(provides_type, [], first_party=True, recursive=False)

    return ThirdPartySymbolMapping(
        FrozenDict(
            (resolve_name, FrozenTrieNode(mapping)) for resolve_name, mapping in mappings.items()
        )
    )


class ConflictingJvmArtifactVersion(ValueError):
    def __init__(
        self, group: str, artifact: str, required_version: str, found_coordinate: Coordinate
    ) -> None:
        self.group: str = group
        self.artifact: str = artifact
        self.required_version: str = required_version
        self.found_coordinate: Coordinate = found_coordinate


class MissingJvmArtifacts(ValueError):
    def __init__(self, coordinates: Iterable[Coordinate | UnversionedCoordinate]) -> None:
        self.coordinates: tuple[Coordinate | UnversionedCoordinate, ...] = tuple(coordinates)


def find_jvm_artifacts_or_raise(
    required_coordinates: Iterable[Coordinate | UnversionedCoordinate],
    resolve: str,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
) -> frozenset[Address]:
    remaining_coordinates: set[Coordinate | UnversionedCoordinate] = set(required_coordinates)

    addresses: set[Address] = set()
    for tgt in jvm_artifact_targets:
        if tgt[JvmResolveField].normalized_value(jvm) != resolve:
            continue

        artifact = ArtifactRequirement.from_jvm_artifact_target(tgt)
        found_coordinates: set[Coordinate | UnversionedCoordinate] = set()
        for coordinate in remaining_coordinates:
            if isinstance(coordinate, Coordinate):
                if (
                    artifact.coordinate.group != coordinate.group
                    or artifact.coordinate.artifact != coordinate.artifact
                ):
                    continue
                if artifact.coordinate.version != coordinate.version:
                    raise ConflictingJvmArtifactVersion(
                        group=coordinate.group,
                        artifact=coordinate.artifact,
                        required_version=coordinate.version,
                        found_coordinate=artifact.coordinate,
                    )
            elif isinstance(coordinate, UnversionedCoordinate):
                if (
                    artifact.coordinate.group != coordinate.group
                    or artifact.coordinate.artifact != coordinate.artifact
                ):
                    continue

            found_coordinates.add(coordinate)

        if found_coordinates:
            remaining_coordinates.difference_update(found_coordinates)
            addresses.add(tgt.address)

    if remaining_coordinates:
        raise MissingJvmArtifacts(remaining_coordinates)

    return frozenset(addresses)


def rules():
    return collect_rules()
