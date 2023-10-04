# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from pants.build_graph.address import Address as Address
from pants.build_graph.address import AddressInput as AddressInput  # noqa: F401: rexport.
from pants.build_graph.address import BuildFileAddress as BuildFileAddress  # noqa: F401: rexport.
from pants.build_graph.address import (  # noqa: F401: rexport.
    BuildFileAddressRequest as BuildFileAddressRequest,
)
from pants.build_graph.address import MaybeAddress as MaybeAddress  # noqa: F401: rexport.
from pants.build_graph.address import ResolveError
from pants.engine.collection import Collection
from pants.util.strutil import bullet_list


def assert_single_address(addresses: Sequence[Address]) -> None:
    """Assert that exactly one address must be contained in the collection."""
    if len(addresses) == 0:
        raise ResolveError("No targets were matched.")
    if len(addresses) > 1:
        raise ResolveError(
            "Expected a single target, but was given multiple targets.\n\n"
            f"Did you mean one of these?\n\n{bullet_list(address.spec for address in addresses)}"
        )


class Addresses(Collection[Address]):
    def expect_single(self) -> Address:
        assert_single_address(self)
        return self[0]


@dataclass(frozen=True)
class UnparsedAddressInputs:
    """Raw addresses that have not been parsed yet.

    You can convert these into fully normalized `Addresses` and `Targets` like this:

        await Get(Addresses, UnparsedAddressInputs(["//:tgt1", "//:tgt2"], owning_address=None)
        await Get(Targets, UnparsedAddressInputs([...], owning_address=Address("original"))

    This is intended for contexts where the user specifies addresses outside of the `dependencies`
    field, such as through an option or a special field on a target that is not normal
    `dependencies`. You should not use this to resolve the `dependencies` field; use
    `await Get(Addresses, DependenciesRequest)` for that.

    If the addresses are coming from a target's fields, set `owning_address` so that relative
    references like `:sibling` work properly.

    Unlike the `dependencies` field, this type does not work with `!` and `!!` ignores.

    Set `description_of_origin` to a value like "CLI arguments" or "the `dependencies` field
    from {tgt.address}". It is used for better error messages.
    """

    values: tuple[str, ...]
    relative_to: str | None
    description_of_origin: str
    skip_invalid_addresses: bool

    def __init__(
        self,
        values: Iterable[str],
        *,
        owning_address: Address | None,
        description_of_origin: str,
        skip_invalid_addresses: bool = False,
    ) -> None:
        object.__setattr__(self, "values", tuple(values))
        object.__setattr__(
            self, "relative_to", owning_address.spec_path if owning_address else None
        )
        object.__setattr__(self, "description_of_origin", description_of_origin)
        object.__setattr__(self, "skip_invalid_addresses", skip_invalid_addresses)
