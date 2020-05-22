# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Sequence

from pants.base.exceptions import ResolveError
from pants.base.specs import OriginSpec
from pants.build_graph.address import Address as Address
from pants.build_graph.address import BuildFileAddress as BuildFileAddress
from pants.engine.collection import Collection


def assert_single_address(addresses: Sequence[Address]) -> None:
    """Assert that exactly one address must be contained in the collection."""
    if len(addresses) == 0:
        raise ResolveError("No targets were matched.")
    if len(addresses) > 1:
        output = "\n  * ".join(address.spec for address in addresses)
        raise ResolveError(
            "Expected a single target, but was given multiple targets.\n\n"
            f"Did you mean one of:\n  * {output}"
        )


class Addresses(Collection[Address]):
    def expect_single(self) -> Address:
        assert_single_address(self)
        return self[0]


@dataclass(frozen=True)
class AddressWithOrigin:
    """A BuildFileAddress along with the cmd-line spec it was generated from."""

    address: Address
    origin: OriginSpec


class AddressesWithOrigins(Collection[AddressWithOrigin]):
    def expect_single(self) -> AddressWithOrigin:
        assert_single_address([address_with_origin.address for address_with_origin in self])
        return self[0]


class BuildFileAddresses(Collection[BuildFileAddress]):
    """NB: V2 should generally use Addresses instead of BuildFileAddresses."""
