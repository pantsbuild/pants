# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.addresses import Address
from pants.jvm.dependency_inference.package_prefix_tree import PackageRootedDependencyMap


def test_package_rooted_dependency_map() -> None:
    dep_map = PackageRootedDependencyMap()

    a = Address("a")
    dep_map.add_top_level_type(type_="org.pantsbuild.Foo", address=a)
    # An exact match yields the exact matching address
    assert dep_map.addresses_for_type("org.pantsbuild.Foo") == frozenset([a])
    # A miss returns nothing
    assert dep_map.addresses_for_type("org.Foo") == frozenset()
    assert dep_map.addresses_for_type("org.other.Foo") == frozenset()

    b = Address("b")
    dep_map.add_top_level_type(type_="org.pantsbuild.Baz", address=b)
    # Again, exact matches yield exact providers
    assert dep_map.addresses_for_type("org.pantsbuild.Foo") == frozenset([a])
    assert dep_map.addresses_for_type("org.pantsbuild.Baz") == frozenset([b])
    # Misses result in nothing.
    assert dep_map.addresses_for_type("org.Foo") == frozenset()
    assert dep_map.addresses_for_type("org.other.Foo") == frozenset()
