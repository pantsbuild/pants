# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Tuple, TypeVar, Union

K = TypeVar("K")
V = TypeVar("V")


class FrozenDict(Mapping[K, V]):
    """A wrapper around a normal `dict` that removes all methods to mutate the instance and that
    implements __hash__.

    This should be used instead of normal dicts when working with the engine because normal dicts
    are not safe to use.
    """

    def __init__(self, item: Optional[Union[Mapping[K, V], Iterable[Tuple[K, V]]]] = None) -> None:
        """Creates a `FrozenDict` from a mapping object or a sequence of tuples representing
        entries.

        These value should be immutable and hashable, but this collection does not do any validation
        that that is true.
        """
        self._data: Dict[K, V] = dict(item)  # type: ignore[arg-type]

    def __getitem__(self, k: K) -> V:
        return self._data[k]

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    def __reversed__(self) -> Iterator[K]:
        return reversed(tuple(self._data))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, FrozenDict):
            return NotImplemented
        return tuple(self.items()) == tuple(other.items())

    def __hash__(self) -> int:
        try:
            return hash(tuple(self.items()))
        except TypeError as e:
            raise TypeError(
                "Even though you are using a `FrozenDict`, the underlying values are not hashable. "
                "Please use hashable and immutable types for the underlying values, e.g. use "
                f"tuples instead of lists and use FrozenOrderedSet instead of set().\n\n"
                f"Original error message: {repr(e)}"
            )

    def __repr__(self) -> str:
        return f"FrozenDict({repr(self._data)})"
