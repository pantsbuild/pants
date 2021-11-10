# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# First-party package mapping
# -----------------------------------------------------------------------------------------------


class SymbolMap:
    """A mapping of JVM package names to owning addresses."""

    def __init__(self):
        self._symbol_map: dict[str, set[Address]] = defaultdict(set)

    def add_symbol(self, symbol: str, address: Address):
        """Declare a single Address as a provider of a symbol."""
        self._symbol_map[symbol].add(address)

    def addresses_for_symbol(self, symbol: str) -> frozenset[Address]:
        """Returns the set of addresses that provide the passed symbol.

        :param symbol: a fully-qualified JVM symbol (e.g. `foo.bar.Thing`).
        """
        return frozenset(self._symbol_map[symbol])

    def merge(self, other: SymbolMap) -> None:
        """Merge 'other' into this dependency map."""
        for symbol, addresses in other._symbol_map.items():
            self._symbol_map[symbol] |= addresses

    def to_json_dict(self):
        return {
            "symbol_map": {
                sym: [str(addr) for addr in addrs] for sym, addrs in self._symbol_map.items()
            },
        }

    def __repr__(self) -> str:
        symbol_map = ", ".join(
            f"{ty}:{', '.join(str(addr) for addr in addrs)}"
            for ty, addrs in self._symbol_map.items()
        )
        return f"SymbolMap(symbol_map={symbol_map})"


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

    return FirstPartySymbolMapping(merged_dep_map)


def rules():
    return collect_rules()
