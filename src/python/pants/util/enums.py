# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from typing import FrozenSet, Mapping, TypeVar


class EnumMatchError(ValueError):
    """Issue when using match() on an enum."""


class InexhaustiveMatchError(EnumMatchError):
    """Not all values of the enum specified in the pattern match."""


class UnrecognizedMatchError(EnumMatchError):
    """A value is used that is not a part of the enum."""


_E = TypeVar("_E", bound=Enum)
_V = TypeVar("_V")


def match(enum_instance: _E, enum_values_to_results: Mapping[_E, _V]) -> _V:
    # TODO: consider memoizing the result of this entire method, as well as the value of
    # `all_instances` for a given enum class!
    all_instances: FrozenSet[_E] = frozenset(type(enum_instance))
    unrecognized_values = [value for value in enum_values_to_results if value not in all_instances]
    missing_values = [value for value in all_instances if value not in enum_values_to_results]
    if unrecognized_values:
        raise UnrecognizedMatchError(
            f"Match includes values not defined in the enum. Unrecognized: {unrecognized_values}"
        )
    if missing_values:
        raise InexhaustiveMatchError(
            f"All enum values must be covered by the match. Missing: {missing_values}"
        )
    return enum_values_to_results[enum_instance]
