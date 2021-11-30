# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from pants.build_graph.address import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.jvm.dependency_inference.artifact_mapper import AllJvmTypeProvidingTargets
from pants.jvm.target_types import JvmProvidesTypesField
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# First-party package mapping
# -----------------------------------------------------------------------------------------------


class JvmFirstPartyPackageMappingException(Exception):
    pass


class SymbolNamespace(Enum):
    """Represents a "namespace" for a symbol, i.e. is the symbol a generic JVM name or did it
    originate from a particular language (and may be encoded for JVM purposes)."""

    JVM = "jvm"
    SCALA = "scala"


class SymbolMap:
    """A mapping of JVM package names to owning addresses."""

    def __init__(self):
        self._symbol_map: dict[SymbolNamespace, dict[str, set[Address]]] = defaultdict(
            lambda: defaultdict(set)
        )

    def add_symbol(self, symbol: str, namespace: SymbolNamespace, address: Address):
        """Declare a single Address as a provider of a symbol."""
        self._symbol_map[namespace][symbol].add(address)

    def addresses_for_symbol(
        self, symbol: str, namespaces: set[SymbolNamespace]
    ) -> frozenset[Address]:
        """Returns the set of addresses that provide the passed symbol by searching the given symbol
        namespaces.

        :param symbol: a fully-qualified JVM symbol (e.g. `foo.bar.Thing`).
        :param namespaces: a set of `SymbolNamespace` enum instances for the namespaces to search
        """
        result: set[Address] = set()
        for namespace in namespaces:
            result.update(self._symbol_map[namespace][symbol])
        return frozenset(result)

    def merge(self, other: SymbolMap) -> None:
        """Merge 'other' into this dependency map."""
        for namespace, addresses_by_symbol in other._symbol_map.items():
            for symbol, addresses in addresses_by_symbol.items():
                self._symbol_map[namespace][symbol] |= addresses

    def to_json_dict(self):
        return {
            "symbol_map": {
                ns: {ty: [str(addr) for addr in addrs] for ty, addrs in addrs_by_sym}
                for ns, addrs_by_sym in self._symbol_map.items()
            },
        }

    def __repr__(self) -> str:
        return f"SymbolMap({json.dumps(self.to_json_dict())})"


@union
@dataclass(frozen=True)
class FirstPartyMappingRequest:
    """An entry point for a specific implementation of mapping JVM package names to owning targets.

    All implementations will be merged together.

    The addresses should all be file addresses, rather than BUILD addresses.
    """


@dataclass(frozen=True)
class FirstPartySymbolMapping:
    """A merged mapping of package names to owning addresses."""

    symbols: SymbolMap


@rule(level=LogLevel.DEBUG)
async def merge_first_party_module_mappings(
    union_membership: UnionMembership,
    targets_that_provide_types: AllJvmTypeProvidingTargets,
) -> FirstPartySymbolMapping:
    all_mappings = await MultiGet(
        Get(
            SymbolMap,
            FirstPartyMappingRequest,
            marker_cls(),
        )
        for marker_cls in union_membership.get(FirstPartyMappingRequest)
    )

    merged_dep_map = SymbolMap()
    for dep_map in all_mappings:
        merged_dep_map.merge(dep_map)

    # `experimental_provides_types` ("`provides`") can be declared on a `java_sources` target,
    # so each generated `java_source` target will have that `provides` annotation. All that matters
    # here is that _one_ of the souce files amongst the set of sources actually provides that type.

    # Collect each address associated with a `provides` annotation and index by the provided type.
    provided_types: dict[str, set[Address]] = defaultdict(set)
    for tgt in targets_that_provide_types:
        for provided_type in tgt[JvmProvidesTypesField].value or []:
            provided_types[provided_type].add(tgt.address)

    # Check that at least one address declared by each `provides` value actually provides the type:
    for provided_type, provided_addresses in provided_types.items():
        # TODO: Add way to specify all scopes for addresses_for_symbol?
        symbol_addresses = merged_dep_map.addresses_for_symbol(
            provided_type, {SymbolNamespace.JVM, SymbolNamespace.SCALA}
        )
        if not provided_addresses.intersection(symbol_addresses):
            raise JvmFirstPartyPackageMappingException(
                f"The target {next(iter(provided_addresses))} declares that it provides the JVM type "
                f"`{provided_type}`, however, it does not appear to actually provide that type."
            )

    return FirstPartySymbolMapping(merged_dep_map)


def rules():
    return collect_rules()
