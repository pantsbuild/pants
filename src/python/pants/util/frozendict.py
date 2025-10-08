# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Callable, ItemsView, Iterable, Mapping, ValuesView
from typing import TypeVar, cast, overload

from pants.engine.internals.native_engine import FrozenDict as FrozenDict
from pants.util.memo import memoized_method

K = TypeVar("K")
V = TypeVar("V")
T = TypeVar("T")


class LazyFrozenDict(FrozenDict[K, V]):
    """A lazy version of `FrozenDict` where the values are not loaded until referenced."""

    @overload
    def __new__(
        cls, __items: Iterable[tuple[K, Callable[[], V]]], **kwargs: Callable[[], V]
    ) -> LazyFrozenDict[K, V]: ...

    @overload
    def __new__(
        cls, __other: Mapping[K, Callable[[], V]], **kwargs: Callable[[], V]
    ) -> LazyFrozenDict[K, V]: ...

    @overload
    def __new__(cls, **kwargs: Callable[[], V]) -> LazyFrozenDict[K, V]: ...

    def __new__(
        cls,
        *item: Mapping[K, Callable[[], V]] | Iterable[tuple[K, Callable[[], V]]],
        **kwargs: Callable[[], V],
    ) -> LazyFrozenDict[K, V]:
        return super().__new__(cls, *item, **kwargs)  # type: ignore[arg-type]

    def __getitem__(self, k: K) -> V:
        return self._get_value(k)

    @overload
    def get(self, key: K, /) -> V | None: ...
    @overload
    def get(self, key: K, /, default: T = ...) -> V | T: ...

    def get(self, key: K, /, default: T | None = None) -> V | T | None:
        try:
            return self._get_value(key)
        except KeyError:
            return default

    @memoized_method
    def _get_value(self, k: K) -> V:
        return cast("Callable[[], V]", super().__getitem__(k))()

    def items(self) -> ItemsView[K, V]:
        return ItemsView(self)

    def values(self) -> ValuesView[V]:
        return ValuesView(self)
