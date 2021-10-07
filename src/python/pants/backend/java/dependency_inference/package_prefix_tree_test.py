# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.java.dependency_inference.package_prefix_tree import (
    CodeProvence,
    PackageRootedDependencyMap,
)
from pants.engine.addresses import Address


def test_package_rooted_dependency_map() -> None:
    dep_map = PackageRootedDependencyMap()

    a = Address("a")
    dep_map.add_top_level_type(
        package="org.pantsbuild", type_="Foo", address=a, code_provence=CodeProvence.NON_TEST
    )
    # An exact match yields the exact matching address
    assert dep_map.addresses_for_symbol("org.pantsbuild.Foo", {CodeProvence.NON_TEST}) == frozenset(
        [a]
    )
    # A miss with a package match yields all providers of the package
    assert dep_map.addresses_for_symbol("org.pantsbuild.Bar", {CodeProvence.NON_TEST}) == frozenset(
        [a]
    )
    # A miss without a package map returns nothing
    assert dep_map.addresses_for_symbol("org.Foo", {CodeProvence.NON_TEST}) == frozenset()
    assert dep_map.addresses_for_symbol("org.other.Foo", {CodeProvence.NON_TEST}) == frozenset()

    b = Address("b")
    dep_map.add_top_level_type(
        package="org.pantsbuild", type_="Baz", address=b, code_provence=CodeProvence.NON_TEST
    )
    # Again, exact matches yield exact providers
    assert dep_map.addresses_for_symbol("org.pantsbuild.Foo", {CodeProvence.NON_TEST}) == frozenset(
        [a]
    )
    assert dep_map.addresses_for_symbol("org.pantsbuild.Baz", {CodeProvence.NON_TEST}) == frozenset(
        [b]
    )
    # But package-only match yields all providers of that package.
    assert dep_map.addresses_for_symbol("org.pantsbuild.Bar", {CodeProvence.NON_TEST}) == frozenset(
        [a, b]
    )
    # And total misses result in nothing.
    assert dep_map.addresses_for_symbol("org.Foo", {CodeProvence.NON_TEST}) == frozenset()
    assert dep_map.addresses_for_symbol("org.other.Foo", {CodeProvence.NON_TEST}) == frozenset()

    c = Address("c")
    # We can also add a package provider manually.
    dep_map.add_package("org.pantsbuild", c, CodeProvence.NON_TEST)
    # It will be included in the event of a package-only match:
    assert dep_map.addresses_for_symbol("org.pantsbuild.Bar", {CodeProvence.NON_TEST}) == frozenset(
        [a, b, c]
    )

    # Package matching also works if the package alone is passed as a symbol:
    assert dep_map.addresses_for_symbol("org.pantsbuild", {CodeProvence.NON_TEST}) == frozenset(
        [a, b, c]
    )
    # But note that we can't distinguish a FQT from a package:
    assert dep_map.addresses_for_symbol(
        "org.pantsbuild.other.package", {CodeProvence.NON_TEST}
    ) == frozenset([a, b, c])

    d = Address("d")
    # But if we know about org.pantsbuild.other.package, the above doesn't happen:
    dep_map.add_package("org.pantsbuild.other.package", d, CodeProvence.NON_TEST)
    assert dep_map.addresses_for_symbol(
        "org.pantsbuild.other.package", {CodeProvence.NON_TEST}
    ) == frozenset([d])


def test_package_rooted_dependency_map_errors() -> None:
    dep_map = PackageRootedDependencyMap()
    a = Address("a")
    b = Address("b")

    dep_map.add_top_level_type(
        package="org.pantsbuild", type_="Foo", address=a, code_provence=CodeProvence.NON_TEST
    )
    # Adding this type again is fine as long as the address is the same
    dep_map.add_top_level_type(
        package="org.pantsbuild", type_="Foo", address=a, code_provence=CodeProvence.NON_TEST
    )
    # But trying to associate it to a different address is an error:
    with pytest.raises(PackageRootedDependencyMap.ConflictingTypeOwnershipError):
        dep_map.add_top_level_type(
            package="org.pantsbuild", type_="Foo", address=b, code_provence=CodeProvence.NON_TEST
        )

    other_map = PackageRootedDependencyMap()
    other_map.add_top_level_type(
        package="org.pantsbuild", type_="Foo", address=b, code_provence=CodeProvence.NON_TEST
    )

    # Trying to merge in a conflict causes the same error:
    with pytest.raises(PackageRootedDependencyMap.ConflictingTypeOwnershipError):
        dep_map.merge(other_map)
