# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pants.build_graph.address import Address
from pants.engine.environment import EnvironmentName
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmTypeProvidingTargets,
    FrozenTrieNode,
    SymbolNamespace,
    ThirdPartySymbolMapping,
)
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmProvidesTypesField, JvmResolveField
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# First-party package mapping
# -----------------------------------------------------------------------------------------------


_ResolveName = str


class JvmFirstPartyPackageMappingException(Exception):
    pass


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class FirstPartyMappingRequest:
    """An entry point for a specific implementation of mapping JVM package names to owning targets.

    All implementations will be merged together.

    The addresses should all be file addresses, rather than BUILD addresses.
    """


class SymbolMap(FrozenDict[_ResolveName, FrozenTrieNode]):
    """The first party symbols provided by a single inference implementation."""


@dataclass(frozen=True)
class SymbolMapping:
    """The merged first and third party symbols provided by all inference implementations."""

    mapping_roots: FrozenDict[_ResolveName, FrozenTrieNode]

    def addresses_for_symbol(
        self, symbol: str, resolve: str
    ) -> FrozenDict[SymbolNamespace, FrozenOrderedSet[Address]]:
        node = self.mapping_roots.get(resolve)
        # Note that it's possible to have a resolve with no associated artifacts.
        if not node:
            return FrozenDict()
        return node.addresses_for_symbol(symbol)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "symbol_map": {
                resolve: node.to_json_dict() for resolve, node in self.mapping_roots.items()
            }
        }


@rule(level=LogLevel.DEBUG)
async def merge_symbol_mappings(
    union_membership: UnionMembership,
    targets_that_provide_types: AllJvmTypeProvidingTargets,
    jvm: JvmSubsystem,
    third_party_mapping: ThirdPartySymbolMapping,
) -> SymbolMapping:
    all_firstparty_mappings = await MultiGet(
        Get(
            SymbolMap,
            FirstPartyMappingRequest,
            marker_cls(),
        )
        for marker_cls in union_membership.get(FirstPartyMappingRequest)
    )
    all_mappings: list[FrozenDict[_ResolveName, FrozenTrieNode]] = [
        *all_firstparty_mappings,
        third_party_mapping,
    ]

    resolves = {resolve for mapping in all_mappings for resolve in mapping.keys()}
    mapping = SymbolMapping(
        FrozenDict(
            (
                resolve,
                FrozenTrieNode.merge(
                    mapping[resolve] for mapping in all_mappings if resolve in mapping
                ),
            )
            for resolve in resolves
        )
    )

    # `experimental_provides_types` ("`provides`") can be declared on a `java_sources` target,
    # so each generated `java_source` target will have that `provides` annotation. All that matters
    # here is that _one_ of the souce files amongst the set of sources actually provides that type.

    # Collect each address associated with a `provides` annotation and index by the provided type.
    provided_types: dict[tuple[str, str], set[Address]] = defaultdict(set)
    for tgt in targets_that_provide_types:
        resolve = tgt[JvmResolveField].normalized_value(jvm)
        for provided_type in tgt[JvmProvidesTypesField].value or []:
            provided_types[(resolve, provided_type)].add(tgt.address)

    # Check that at least one address declared by each `provides` value actually provides the type:
    for (resolve, provided_type), provided_addresses in provided_types.items():
        symbol_addresses = mapping.addresses_for_symbol(provided_type, resolve=resolve)
        logger.info(f"addresses for {provided_type} in {resolve}:\n  {symbol_addresses}")
        if not any(
            provided_addresses.intersection(ns_addresses)
            for ns_addresses in symbol_addresses.values()
        ):
            raise JvmFirstPartyPackageMappingException(
                f"The target {next(iter(provided_addresses))} declares that it provides the JVM type "
                f"`{provided_type}`, however, it does not appear to actually provide that type."
            )

    return mapping


def rules():
    return collect_rules()
