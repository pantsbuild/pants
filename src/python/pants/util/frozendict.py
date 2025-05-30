# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any, TypeVar, cast, overload

from pants.util.memo import memoized_method
from pants.util.strutil import softwrap

K = TypeVar("K")
V = TypeVar("V")


class FrozenDict(Mapping[K, V]):
    """A wrapper around a normal `dict` that removes all methods to mutate the instance and that
    implements __hash__.

    This should be used instead of normal dicts when working with the engine because normal dicts
    are not safe to use.
    """

    @overload
    def __init__(self, __items: Iterable[tuple[K, V]], **kwargs: V) -> None: ...

    @overload
    def __init__(self, __other: Mapping[K, V], **kwargs: V) -> None: ...

    @overload
    def __init__(self, **kwargs: V) -> None: ...

    def __init__(self, *item: Mapping[K, V] | Iterable[tuple[K, V]], **kwargs: V) -> None:
        """Creates a `FrozenDict` with arguments accepted by `dict` that also must be hashable."""
        if len(item) > 1:
            raise ValueError(
                f"{type(self).__name__} was called with {len(item)} positional arguments but it expects one."
            )

        # NB: Keep the variable name `_data` in sync with `externs/mod.rs`.
        self._data = dict(item[0]) if item else dict()
        self._data.update(**kwargs)

        # NB: We eagerly compute the hash to validate that the values are hashable and to avoid
        # performing the calculation multiple times. This can be revisited if it's found to be a
        # performance bottleneck.
        self._hash = self._calculate_hash()

    @classmethod
    def deep_freeze(cls, data: Mapping[K, V]) -> FrozenDict[K, V]:
        """Convert mutable values to their frozen counter parts.

        Sets and lists are turned into tuples and dicts into FrozenDicts.
        """

        def _freeze(obj):
            if isinstance(obj, dict):
                return cls.deep_freeze(obj)
            if isinstance(obj, (list, set)):
                return tuple(map(_freeze, obj))
            return obj

        return cls({k: _freeze(v) for k, v in data.items()})

    @staticmethod
    def frozen(to_freeze: Mapping[K, V]) -> FrozenDict[K, V]:
        """Returns a `FrozenDict` containing the keys and values of `to_freeze`.

        If `to_freeze` is already a `FrozenDict`, returns the same object.
        """

        return to_freeze if isinstance(to_freeze, FrozenDict) else FrozenDict(to_freeze)

    def __getitem__(self, k: K) -> V:
        return self._data[k]

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    def __reversed__(self) -> Iterator[K]:
        return reversed(tuple(self._data))

    def __eq__(self, other: Any) -> Any:
        # defer to dict's __eq__
        return self._data == other

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, FrozenDict):
            return NotImplemented
        # If sorting each of these on every __lt__ call ends up being a problem we could consider
        # optimising this, by, for instance, sorting on construction.
        return sorted(self._data.items()) < sorted(other._data.items())

    def __or__(self, other: Any) -> FrozenDict[K, V]:
        if isinstance(other, FrozenDict):
            other = other._data
        elif not isinstance(other, Mapping):
            return NotImplemented
        return FrozenDict(self._data | other)

    def __ror__(self, other: Any) -> FrozenDict[K, V]:
        if isinstance(other, FrozenDict):
            other = other._data
        elif not isinstance(other, Mapping):
            return NotImplemented
        return FrozenDict(other | self._data)

    def _calculate_hash(self) -> int:
        try:
            h = 0
            for pair in self._data.items():
                # xor is commutative, i.e. we get the same hash no matter the order of items. This
                # "relies" on "hash" of the individual elements being unpredictable enough that such
                # a naive aggregation is okay. In addition, the Python hash isn't / shouldn't be
                # used for cryptographically sensitive purposes.
                h ^= hash(pair)
            return h
        except TypeError as e:
            raise TypeError(
                softwrap(
                    f"""
                    Even though you are using a `{type(self).__name__}`, the underlying values are
                    not hashable. Please use hashable (and preferably immutable) types for the
                    underlying values, e.g. use tuples instead of lists and use FrozenOrderedSet
                    instead of set().

                    Original error message: {e}

                    Value: {self}
                    """
                )
            )

    def __hash__(self) -> int:
        return self._hash

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._data!r})"


class LazyFrozenDict(FrozenDict[K, V]):
    """A lazy version of `FrozenDict` where the values are not loaded until referenced."""

    @overload
    def __init__(
        self, __items: Iterable[tuple[K, Callable[[], V]]], **kwargs: Callable[[], V]
    ) -> None: ...

    @overload
    def __init__(self, __other: Mapping[K, Callable[[], V]], **kwargs: Callable[[], V]) -> None: ...

    @overload
    def __init__(self, **kwargs: Callable[[], V]) -> None: ...

    def __init__(
        self,
        *item: Mapping[K, Callable[[], V]] | Iterable[tuple[K, Callable[[], V]]],
        **kwargs: Callable[[], V],
    ) -> None:
        super().__init__(*item, **kwargs)  # type: ignore[arg-type]

    def __getitem__(self, k: K) -> V:
        return self._get_value(k)

    @memoized_method
    def _get_value(self, k: K) -> V:
        return cast("Callable[[], V]", self._data[k])()
