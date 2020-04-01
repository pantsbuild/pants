# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.base.specs import (
    AddressSpecsMatcher,
    AscendantAddresses,
    DescendantAddresses,
    SiblingAddresses,
    SingleAddress,
    more_specific,
)
from pants.build_graph.address import Address
from pants.engine.legacy.structs import TargetAdaptor


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


class AddressSpecsMatcherTest(unittest.TestCase):
    def _make_target(self, address: str, **kwargs) -> TargetAdaptor:
        return TargetAdaptor(address=Address.parse(address), **kwargs)

    def _matches(self, matcher: AddressSpecsMatcher, target: TargetAdaptor) -> bool:
        return matcher.matches_target_address_pair(target.address, target)

    def test_match_target(self):
        matcher = AddressSpecsMatcher(tags=["-a", "+b"])

        untagged_target = self._make_target(address="//:untagged")
        b_tagged_target = self._make_target(address="//:b-tagged", tags=["b"])
        a_and_b_tagged_target = self._make_target(address="//:a-and-b-tagged", tags=["a", "b"])
        none_tagged_target = self._make_target(address="//:none-tagged-target", tags=None)

        def matches(tgt):
            return self._matches(matcher, tgt)

        assert not matches(untagged_target)
        assert matches(b_tagged_target)
        assert not matches(a_and_b_tagged_target)
        # This is mostly a test to verify an exception isn't thrown.
        assert not matches(none_tagged_target)
