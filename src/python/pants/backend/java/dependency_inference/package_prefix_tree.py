# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict

from pants.engine.addresses import Address


class PackageRootedDependencyMap:
    """A utility class for mapping Java FQTs and packages to owning source Addresses.

    This class treats Java packages as logically opaque strings, ignoring the
    apparent hierarchy (which is itself misleading).  For example, the packages
    "org.pantsbuild" and "org.pantsbuild.foo" are treated as completely unrelated
    packages by this mapping implementation.

    We keep track of two things:
        * Which Address provides a fully qualified symbol
        * The set of Addresses that provide a given package
    """

    class ConflictingTypeOwnershipError(Exception):
        """Raised when a Java FQT appears to be provided by more than one Address."""

    def __init__(self):
        self._type_map: dict[str, Address] = {}
        self._package_map: dict[str, set[Address]] = defaultdict(set)

    def add_top_level_type(self, package: str, type_: str, address: Address):
        """Declare a single Address as the provider of a top level type.

        Raises ConflictingTypeOwnershipError if another address is already the provider
        of the passed FQT.

        This method also associates the address with the type's package, and there can
        be more than one address associated with a given package.
        """
        fqt = ".".join([package, type_])
        if fqt in self._type_map and self._type_map[fqt] != address:
            raise PackageRootedDependencyMap.ConflictingTypeOwnershipError(
                f"Attempted register '{address}' as provider of fully qualified type"
                f" '{fqt}', but it is already provided by '{self._type_map[fqt]}'"
            )
        self._type_map[fqt] = address
        self._package_map[package].add(address)

    def add_package(self, package: str, address: Address):
        """Add an address as one of the providers of a package."""
        self._package_map[package].add(address)

    def addresses_for_symbol(self, symbol: str) -> frozenset[Address]:
        """Returns the set of addresses that provide the passed symbol.

        `symbol` should be a fully qualified Java type (FQT) (e.g. `foo.bar.Thing`),
        or a Java package (e.g. `foo.bar`).

        We first check if the symbol has an exact matching provider address for the FQT.
        If it does, only that address is returned.  We then check if the symbol is
        actually a package, in which case we return the set of addresses that provide
        that package.

        We then chop off the rightmost part of the symbol (e.g. `foo.bar.Thing` becomes
        `foo.bar`) and repeat the above process until there is nothing left.  If nothing
        is found, an empty set is returned.
        """
        parts = symbol.split(".")
        for num_parts in range(len(parts), 0, -1):
            prefix = ".".join(parts[:num_parts])
            if prefix in self._type_map:
                return frozenset([self._type_map[prefix]])
            if prefix in self._package_map:
                return frozenset(self._package_map[prefix])
        return frozenset()

    def merge(self, other: PackageRootedDependencyMap):
        """Merge 'other' into this dependency map.

        Raises ConflictingTypeOwnershipError if 'other' has an FQT mapped to an address that
        conflicts with this dep map.
        """

        for type_, address in other._type_map.items():
            if type_ in self._type_map and self._type_map[type_] != address:
                raise PackageRootedDependencyMap.ConflictingTypeOwnershipError(
                    'Conflicting ownership of FQT "{type_}": both {self._type_map[type_]}'
                    " and {address} appear to provide this type."
                )
            self._type_map[type_] = address
        for package, addresses in other._package_map.items():
            self._package_map[package] |= addresses

    def to_json_dict(self):
        return {
            "type_map": {ty: str(addr) for ty, addr in self._type_map.items()},
            "package_map": {
                pkg: [str(addr) for addr in addrs] for pkg, addrs in self._package_map.items()
            },
        }

    def __repr__(self) -> str:
        type_map = ", ".join(f"{ty}:{addr}" for ty, addr in self._type_map.items())
        package_map = ", ".join(
            f"{pkg}:{', '.join(str(addr) for addr in addrs)}"
            for pkg, addrs in self._package_map.items()
        )
        return f"PackageRootedDependencyMap(type_map={type_map}, package_map={package_map})"
