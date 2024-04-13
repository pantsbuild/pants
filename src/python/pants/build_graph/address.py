# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Iterable

from pants.base.exceptions import MappingError
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import (  # noqa: F401
    BANNED_CHARS_IN_GENERATED_NAME as BANNED_CHARS_IN_GENERATED_NAME,
)
from pants.engine.internals.native_engine import (  # noqa: F401
    BANNED_CHARS_IN_PARAMETERS as BANNED_CHARS_IN_PARAMETERS,
)
from pants.engine.internals.native_engine import (  # noqa: F401
    BANNED_CHARS_IN_TARGET_NAME as BANNED_CHARS_IN_TARGET_NAME,
)
from pants.engine.internals.native_engine import Address as Address  # noqa: F401
from pants.engine.internals.native_engine import AddressInput as AddressInput  # noqa: F401
from pants.engine.internals.native_engine import (  # noqa: F401
    AddressParseException as AddressParseException,
)
from pants.engine.internals.native_engine import (  # noqa: F401
    InvalidAddressError as InvalidAddressError,
)
from pants.engine.internals.native_engine import (  # noqa: F401
    InvalidParametersError as InvalidParametersError,
)
from pants.engine.internals.native_engine import (  # noqa: F401
    InvalidSpecPathError as InvalidSpecPathError,
)
from pants.engine.internals.native_engine import (  # noqa: F401
    InvalidTargetNameError as InvalidTargetNameError,
)
from pants.engine.internals.native_engine import (  # noqa: F401
    UnsupportedWildcardError as UnsupportedWildcardError,
)
from pants.util.strutil import bullet_list, softwrap


@dataclass(frozen=True)
class BuildFileAddressRequest(EngineAwareParameter):
    """A request to find the BUILD file path for an address."""

    address: Address
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

    def debug_hint(self) -> str:
        return self.address.spec


@dataclass(frozen=True)
class BuildFileAddress:
    """An address, along with the relative file path of its BUILD file."""

    address: Address
    rel_path: str


class ResolveError(MappingError):
    """Indicates an error resolving targets."""

    @classmethod
    def did_you_mean(
        cls,
        bad_address: Address,
        *,
        description_of_origin: str,
        known_names: Iterable[str],
        namespace: str,
    ) -> ResolveError:
        return cls(
            softwrap(
                f"""
                The address {bad_address} from {description_of_origin} does not exist.

                The target name ':{bad_address.target_name}' is not defined in the directory
                {namespace}. Did you mean one of these target names?\n
                """
                + bullet_list(f":{name}" for name in known_names)
            )
        )


@dataclass(frozen=True)
class MaybeAddress:
    """A target address, or an error if it could not be created.

    Use `Get(MaybeAddress, AddressInput)`, rather than the fallible variant
    `Get(Address, AddressInput)`.

    Note that this does not validate the address's target actually exists. It only validates that
    the address is well-formed and that its spec_path exists.

    Reminder: you may need to catch errors when creating the input `AddressInput` if the address is
    not well-formed.
    """

    val: Address | ResolveError
