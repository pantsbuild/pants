# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable, Optional, Type, TypeVar, cast

from pants.util.frozendict import FrozenDict

_T = TypeVar("_T", bound="FrozenDictUtilsMixin")
_T2 = TypeVar("_T2", bound="FrozenDictUtilsMixin")


class FrozenDictUtilsMixin(FrozenDict[str, Optional[str]]):
    """Generic mixin class for frozen dicts, to work with lists of "KEY[=VALUE]" strings."""

    @classmethod
    def from_strings(cls: Type[_T], strings: Iterable[str]) -> _T:
        return cls(
            {
                key: value if eq else None
                for key, eq, value in [pair.partition("=") for pair in strings]
            }
        )

    @property
    def to_strings(self) -> tuple[str, ...]:
        """This will return all pairs as "KEY=VALUE" and "KEY" for `None` values."""
        return tuple(sorted({*self.to_pairs, *self.to_keys_none_value}))

    @property
    def to_pairs(self) -> tuple[str, ...]:
        """Returns all "KEY=VALUE" pairs.

        This will exclude any keys with a `None` value.

        Complements `to_keys_none_value`.
        """
        return tuple(sorted("=".join(s for s in [key, value] if s) for key, value in self.items()))

    @property
    def to_keys_none_value(self) -> set[str]:
        """Returns all "KEY" values.

        This will only include keys with a `None` value.

        Complements `to_pairs`.
        """
        return set(sorted(key for key, value in self.items() if value is None))

    def merge(self: _T, raw_other: _T2 | Iterable[str]) -> _T:
        """Update this dict, with the values of the other, and return the merged result."""
        if not raw_other:
            return self

        other = (
            raw_other
            if isinstance(raw_other, FrozenDictUtilsMixin)
            else FrozenDictUtilsMixin.from_strings(raw_other)
        )
        return type(self)({**cast(dict, self), **cast(dict, other)})
