# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpecs,
    AscendantAddresses,
    DescendantAddresses,
    FilesystemGlobSpec,
    FilesystemLiteralSpec,
    FilesystemSpecs,
    SiblingAddresses,
)


def test_address_specs_more_specific() -> None:
    literal_addr = AddressLiteralSpec(path_component="foo/bar", target_component="baz")
    sibling_addresses = SiblingAddresses(directory="foo/bar")
    ascendant_addresses = AscendantAddresses(directory="foo/bar")
    descendant_addresses = DescendantAddresses(directory="foo/bar")

    assert literal_addr == AddressSpecs.more_specific(literal_addr, None)
    assert literal_addr == AddressSpecs.more_specific(literal_addr, sibling_addresses)
    assert literal_addr == AddressSpecs.more_specific(literal_addr, ascendant_addresses)
    assert literal_addr == AddressSpecs.more_specific(literal_addr, descendant_addresses)
    assert literal_addr == AddressSpecs.more_specific(None, literal_addr)
    assert literal_addr == AddressSpecs.more_specific(sibling_addresses, literal_addr)
    assert literal_addr == AddressSpecs.more_specific(ascendant_addresses, literal_addr)
    assert literal_addr == AddressSpecs.more_specific(descendant_addresses, literal_addr)

    assert sibling_addresses == AddressSpecs.more_specific(sibling_addresses, None)
    assert sibling_addresses == AddressSpecs.more_specific(sibling_addresses, ascendant_addresses)
    assert sibling_addresses == AddressSpecs.more_specific(sibling_addresses, descendant_addresses)
    assert sibling_addresses == AddressSpecs.more_specific(None, sibling_addresses)
    assert sibling_addresses == AddressSpecs.more_specific(ascendant_addresses, sibling_addresses)
    assert sibling_addresses == AddressSpecs.more_specific(descendant_addresses, sibling_addresses)

    assert ascendant_addresses == AddressSpecs.more_specific(ascendant_addresses, None)
    assert ascendant_addresses == AddressSpecs.more_specific(
        ascendant_addresses, descendant_addresses
    )
    assert ascendant_addresses == AddressSpecs.more_specific(None, ascendant_addresses)
    assert ascendant_addresses == AddressSpecs.more_specific(
        descendant_addresses, ascendant_addresses
    )

    assert descendant_addresses == AddressSpecs.more_specific(descendant_addresses, None)
    assert descendant_addresses == AddressSpecs.more_specific(None, descendant_addresses)


def test_filesystem_specs_more_specific() -> None:
    literal = FilesystemLiteralSpec("foo.txt")
    glob = FilesystemGlobSpec("*.txt")

    assert literal == FilesystemSpecs.more_specific(literal, None)
    assert literal == FilesystemSpecs.more_specific(literal, glob)
    assert literal == FilesystemSpecs.more_specific(None, literal)
    assert literal == FilesystemSpecs.more_specific(glob, literal)

    assert glob == FilesystemSpecs.more_specific(None, glob)
    assert glob == FilesystemSpecs.more_specific(glob, None)
