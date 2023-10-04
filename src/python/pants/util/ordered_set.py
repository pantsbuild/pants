# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""An OrderedSet is a set that remembers its insertion order, and a FrozenOrderedSet is one that is
also immutable.

Based on the library `ordered-set` developed by Robyn Speer and released under the MIT license:
https://github.com/LuminosoInsight/ordered-set.

The library `ordered-set` is itself originally based on a recipe originally posted to ActivateState
Recipes by Raymond Hettiger and released under the MIT license:
http://code.activestate.com/recipes/576694/.
"""

from __future__ import annotations

import itertools
from typing import AbstractSet, Any, Hashable, Iterable, Iterator, MutableSet, Set, TypeVar, cast

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)
_TAbstractOrderedSet = TypeVar("_TAbstractOrderedSet", bound="_AbstractOrderedSet")


class _AbstractOrderedSet(AbstractSet[T]):
    """Common functionality shared between OrderedSet and FrozenOrderedSet."""

    def __init__(self, iterable: Iterable[T] | None = None) -> None:
        # Using a dictionary, rather than using the recipe's original `self |= iterable`, results
        # in a ~20% performance increase for the constructor.
        #
        # NB: Dictionaries are ordered in Python 3.7+.
        self._items: dict[T, None] = {v: None for v in iterable or ()}

    def __len__(self) -> int:
        """Returns the number of unique elements in the set."""
        return len(self._items)

    def __copy__(self: _TAbstractOrderedSet) -> _TAbstractOrderedSet:
        """Return a shallow copy of this object."""
        return self.__class__(self)

    def __contains__(self, key: Any) -> bool:
        """Test if the item is in this ordered set."""
        return key in self._items

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def __reversed__(self) -> Iterator[T]:
        return reversed(tuple(self._items.keys()))

    def __repr__(self) -> str:
        name = self.__class__.__name__
        if not self:
            return f"{name}()"
        return f"{name}({list(self)!r})"

    def __eq__(self, other: Any) -> bool:
        """Returns True if other is the same type with the same elements and same order."""
        if not isinstance(other, self.__class__):
            return NotImplemented
        return len(self._items) == len(other._items) and all(
            x == y for x, y in zip(self._items, other._items)
        )

    def __or__(self: _TAbstractOrderedSet, other: Iterable[T]) -> _TAbstractOrderedSet:  # type: ignore[override]
        return self.union(other)

    def union(self: _TAbstractOrderedSet, *others: Iterable[T]) -> _TAbstractOrderedSet:
        """Combines all unique items.

        Each item's order is defined by its first appearance.
        """
        # Differences with AbstractSet: our set union forces "other" to have the same type. That
        # is, while AbstractSet allows {1, 2, 3} | {(True, False)} resulting in
        # set[int | tuple[bool, bool]], the analogous for descendants  of _TAbstractOrderedSet is
        # not allowed.
        #
        # GOTCHA: given _TAbstractOrderedSet[S]:
        #   if T is a subclass of S => _TAbstractOrderedSet[S] => *appears* to perform
        #     unification but it doesn't
        #   if S is a subclass of T => type error (while AbstractSet would resolve to
        #     AbstractSet[T])
        merged_iterables = itertools.chain([cast(Iterable[T], self)], others)
        return self.__class__(itertools.chain.from_iterable(merged_iterables))

    def __and__(self: _TAbstractOrderedSet, other: Iterable[T]) -> _TAbstractOrderedSet:
        # The parent class's implementation of this is backwards.
        return self.intersection(other)

    def intersection(self: _TAbstractOrderedSet, *others: Iterable[T]) -> _TAbstractOrderedSet:
        """Returns elements in common between all sets.

        Order is defined only by the first set.
        """
        cls = self.__class__
        if not others:
            return cls(self)
        common = set.intersection(*(set(other) for other in others))
        return cls(item for item in self if item in common)

    def difference(self: _TAbstractOrderedSet, *others: Iterable[T]) -> _TAbstractOrderedSet:
        """Returns all elements that are in this set but not the others."""
        cls = self.__class__
        if not others:
            return cls(self)
        other = set.union(*(set(other) for other in others))
        return cls(item for item in self if item not in other)

    def issubset(self, other: Iterable[T]) -> bool:
        """Report whether another set contains this set."""
        try:
            # Fast check for obvious cases
            if len(self) > len(other):  # type: ignore[arg-type]
                return False
        except TypeError:
            pass
        return all(item in other for item in self)

    def issuperset(self, other: Iterable[T]) -> bool:
        """Report whether this set contains another set."""
        try:
            # Fast check for obvious cases
            if len(self) < len(other):  # type: ignore[arg-type]
                return False
        except TypeError:
            pass
        return all(item in self for item in other)

    def __xor__(self: _TAbstractOrderedSet, other: Iterable[T]) -> _TAbstractOrderedSet:  # type: ignore[override]
        return self.symmetric_difference(other)

    def symmetric_difference(
        self: _TAbstractOrderedSet, other: Iterable[T]
    ) -> _TAbstractOrderedSet:
        """Return the symmetric difference of this OrderedSet and another set as a new OrderedSet.
        That is, the new set will contain all elements that are in exactly one of the sets.

        Their order will be preserved, with elements from `self` preceding elements from `other`.
        """
        cls = self.__class__
        diff1 = cls(self).difference(other)
        diff2 = cls(other).difference(self)
        return diff1.union(diff2)


class OrderedSet(_AbstractOrderedSet[T], MutableSet[T]):
    """A mutable set that retains its order.

    This is not safe to use with the V2 engine.
    """

    def add(self, key: T) -> None:
        """Add `key` as an item to this OrderedSet."""
        self._items[key] = None

    def update(self, iterable: Iterable[T]) -> None:
        """Update the set with the given iterable sequence."""
        for item in iterable:
            self.add(item)

    def discard(self, key: T) -> None:
        """Remove an element. Do not raise an exception if absent.

        The MutableSet mixin uses this to implement the .remove() method, which
        *does* raise an error when asked to remove a non-existent item.
        """
        self._items.pop(key, None)

    def clear(self) -> None:
        """Remove all items from this OrderedSet."""
        self._items.clear()

    def difference_update(self, *others: Iterable[T]) -> None:
        """Update this OrderedSet to remove items from one or more other sets."""
        items_to_remove: set[T] = set()
        for other in others:
            items_as_set = set(other)
            items_to_remove |= items_as_set
        self._items = {item: None for item in self._items.keys() if item not in items_to_remove}

    def intersection_update(self, other: Iterable[T]) -> None:
        """Update this OrderedSet to keep only items in another set, preserving their order in this
        set."""
        other = set(other)
        self._items = {item: None for item in self._items.keys() if item in other}

    def symmetric_difference_update(self, other: Iterable[T]) -> None:
        """Update this OrderedSet to remove items from another set, then add items from the other
        set that were not present in this set."""
        items_to_add = [item for item in other if item not in self]
        items_to_remove = cast(Set[T], set(other))
        self._items = {item: None for item in self._items.keys() if item not in items_to_remove}
        for item in items_to_add:
            self._items[item] = None


class FrozenOrderedSet(_AbstractOrderedSet[T_co], Hashable):  # type: ignore[type-var]
    """A frozen (i.e. immutable) set that retains its order.

    This is safe to use with the V2 engine.
    """

    def __init__(self, iterable: Iterable[T_co] | None = None) -> None:
        super().__init__(iterable)
        self.__hash: int | None = None

    def __hash__(self) -> int:
        if self.__hash is None:
            self.__hash = 0
            for item in self._items.keys():
                self.__hash ^= hash(item)
        return self.__hash
