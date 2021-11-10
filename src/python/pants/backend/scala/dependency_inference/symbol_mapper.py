# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pants.backend.scala.dependency_inference.scala_parser import ScalaSourceDependencyAnalysis
from pants.backend.scala.target_types import ScalaSourceField
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.util.logging import LogLevel


class SymbolMap:
    def __init__(self):
        self._symbol_map: dict[str, set[Address]] = defaultdict(set)

    def add_symbol(self, symbol: str, address: Address):
        """Declare a single Address as a provider of a symbol."""
        self._symbol_map[symbol].add(address)

    def addresses_for_symbol(self, symbol: str) -> frozenset[Address]:
        """Returns the set of addresses that provide the passed symbol.

        :param symbol: a fully-qualified Scala symbol (e.g. `foo.bar.Thing`).
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


@dataclass(frozen=True)
class FirstPartyScalaSymbolMapping:
    """A merged mapping of symbol names to owning addresses for Scala code."""

    symbols: SymbolMap


# TODO: add third-party targets here? That would allow us to avoid iterating over AllTargets twice.
#  See `backend/python/dependency_inference/module_mapper.py` for an example.
class AllScalaTargets(Targets):
    pass


@rule(desc="Find all Scala targets in project", level=LogLevel.DEBUG)
def find_all_java_targets(targets: AllTargets) -> AllScalaTargets:
    return AllScalaTargets(tgt for tgt in targets if tgt.has_field(ScalaSourceField))


@rule(desc="Map all first party Scala targets to their symbols", level=LogLevel.DEBUG)
async def map_first_party_scala_targets_to_symbols(
    scala_targets: AllScalaTargets,
) -> FirstPartyScalaSymbolMapping:
    source_files = await MultiGet(
        Get(SourceFiles, SourceFilesRequest([target[ScalaSourceField]])) for target in scala_targets
    )
    source_analysis = await MultiGet(
        Get(ScalaSourceDependencyAnalysis, SourceFiles, source_files)
        for source_files in source_files
    )
    address_and_analysis = zip([t.address for t in scala_targets], source_analysis)

    symbol_map = SymbolMap()
    for address, analysis in address_and_analysis:
        for symbol in analysis.provided_names:
            symbol_map.add_symbol(symbol, address)

    return FirstPartyScalaSymbolMapping(symbol_map)


def rules():
    return collect_rules()
