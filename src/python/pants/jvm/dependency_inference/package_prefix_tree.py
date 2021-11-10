# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict

from pants.engine.addresses import Address


class PackageRootedDependencyMap:
    """A utility class for mapping JVM FQTs to owning source Addresses.

    Keep tracks of which Address provides a fully qualified symbol.
    """

    def __init__(self):
        self._type_map: dict[str, set[Address]] = defaultdict(set)

    def add_top_level_type(self, type_: str, address: Address):
        """Declare a single Address as a provider of a top level type."""
        self._type_map[type_].add(address)

    def addresses_for_type(self, symbol: str) -> frozenset[Address]:
        """Returns the set of addresses that provide the passed type.

        `symbol` should be a fully qualified Java type (FQT) (e.g. `foo.bar.Thing`).
        """
        return frozenset(self._type_map[symbol])

    def merge(self, other: PackageRootedDependencyMap):
        """Merge 'other' into this dependency map."""

        for type_, addresses in other._type_map.items():
            self._type_map[type_] |= addresses

    def to_json_dict(self):
        return {
            "type_map": {ty: [str(addr) for addr in addrs] for ty, addrs in self._type_map.items()},
        }

    def __repr__(self) -> str:
        type_map = ", ".join(
            f"{ty}:{', '.join(str(addr) for addr in addrs)}" for ty, addrs in self._type_map.items()
        )
        return f"PackageRootedDependencyMap(type_map={type_map})"
