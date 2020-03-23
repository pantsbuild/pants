# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.specs import (
    AscendantAddresses,
    DescendantAddresses,
    SiblingAddresses,
    SingleAddress,
    more_specific,
)


def test_more_specific():
    single_address = SingleAddress(directory="foo/bar", name="baz")
    sibling_addresses = SiblingAddresses(directory="foo/bar")
    ascendant_addresses = AscendantAddresses(directory="foo/bar")
    descendant_addresses = DescendantAddresses(directory="foo/bar")

    assert single_address == more_specific(single_address, None)
    assert single_address == more_specific(single_address, sibling_addresses)
    assert single_address == more_specific(single_address, ascendant_addresses)
    assert single_address == more_specific(single_address, descendant_addresses)
    assert single_address == more_specific(None, single_address)
    assert single_address == more_specific(sibling_addresses, single_address)
    assert single_address == more_specific(ascendant_addresses, single_address)
    assert single_address == more_specific(descendant_addresses, single_address)

    assert sibling_addresses == more_specific(sibling_addresses, None)
    assert sibling_addresses == more_specific(sibling_addresses, ascendant_addresses)
    assert sibling_addresses == more_specific(sibling_addresses, descendant_addresses)
    assert sibling_addresses == more_specific(None, sibling_addresses)
    assert sibling_addresses == more_specific(ascendant_addresses, sibling_addresses)
    assert sibling_addresses == more_specific(descendant_addresses, sibling_addresses)

    assert ascendant_addresses == more_specific(ascendant_addresses, None)
    assert ascendant_addresses == more_specific(ascendant_addresses, descendant_addresses)
    assert ascendant_addresses == more_specific(None, ascendant_addresses)
    assert ascendant_addresses == more_specific(descendant_addresses, ascendant_addresses)

    assert descendant_addresses == more_specific(descendant_addresses, None)
    assert descendant_addresses == more_specific(None, descendant_addresses)
