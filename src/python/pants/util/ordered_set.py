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

import itertools
from typing import (
    AbstractSet,
    Any,
    Dict,
    Iterable,
    Iterator,
    MutableSet,
    Optional,
    Set,
    TypeVar,
    Union,
    cast,
)

T = TypeVar("T")


class _AbstractOrderedSet(AbstractSet[T]):
    """Common functionality shared between OrderedSet and FrozenOrderedSet."""

    def __init__(self, iterable: Optional[Iterable[T]] = None) -> None:
        # Using a dictionary, rather than using the recipe's original `self |= iterable`, results
        # in a ~20% performance increase for the constructor.
        #
        # NB: Dictionaries are ordered in Python 3.6+. While this was not formalized until Python
        # 3.7, Python 3.6 uses this behavior; Pants requires CPython 3.6+ to run, so this
        # assumption is safe for us to rely on.
        self._items: Dict[T, None] = {v: None for v in iterable or ()}

    def __len__(self) -> int:
        """Returns the number of unique elements in the set."""
        return len(self._items)

    def __copy__(self) -> "_AbstractOrderedSet[T]":
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
        return all(x == y for x, y in itertools.zip_longest(self._items, other._items))

    def union(self, *others: Iterable[T]) -> "_AbstractOrderedSet[T]":
        """Combines all unique items.

        Each item's order is defined by its first appearance.
        """
        merged_iterables = itertools.chain([self], others)
        return self.__class__(itertools.chain.from_iterable(merged_iterables))

    def __and__(self, other: Iterable[T]) -> "_AbstractOrderedSet[T]":
        # The parent class's implementation of this is backwards.
        return self.intersection(other)

    def intersection(self, *others: Iterable[T]) -> "_AbstractOrderedSet[T]":
        """Returns elements in common between all sets.

        Order is defined only by the first set.
        """
        cls = self.__class__
        if not others:
            return cls(self)
        common = set.intersection(*(set(other) for other in others))
        return cls(item for item in self if item in common)

    def difference(self, *others: Iterable[T]) -> "_AbstractOrderedSet[T]":
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

    def symmetric_difference(self, other: Iterable[T]) -> "_AbstractOrderedSet[T]":
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

    def __copy__(self) -> "OrderedSet[T]":
        return cast(OrderedSet[T], super().__copy__())

    def union(self, *others: Iterable[T]) -> "OrderedSet[T]":
        return cast(OrderedSet[T], super().union(*others))

    def __and__(self, other: Iterable[T]) -> "OrderedSet[T]":
        return cast(OrderedSet[T], super().__and__(other))

    def intersection(self, *others: Iterable[T]) -> "OrderedSet[T]":
        return cast(OrderedSet[T], super().intersection(*others))

    def difference(self, *others: Iterable[T]) -> "OrderedSet[T]":
        return cast(OrderedSet[T], super().difference(*others))

    def symmetric_difference(self, *others: Iterable[T]) -> "OrderedSet[T]":
        return cast(OrderedSet[T], super().symmetric_difference(*others))

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
        items_to_remove: Set[T] = set()
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


class FrozenOrderedSet(_AbstractOrderedSet[T]):
    """A frozen (i.e. immutable) set that retains its order.

    This is safe to use with the V2 engine.
    """

    def __init__(self, iterable: Optional[Iterable[T]] = None) -> None:
        super().__init__(iterable)
        self._hash: Union[int, None] = None

    def __copy__(self) -> "FrozenOrderedSet[T]":
        return cast(FrozenOrderedSet[T], super().__copy__())

    def union(self, *others: Iterable[T]) -> "FrozenOrderedSet[T]":
        return cast(FrozenOrderedSet[T], super().union(*others))

    def __and__(self, other: Iterable[T]) -> "FrozenOrderedSet[T]":
        return cast(FrozenOrderedSet[T], super().__and__(other))

    def intersection(self, *others: Iterable[T]) -> "FrozenOrderedSet[T]":
        return cast(FrozenOrderedSet[T], super().intersection(*others))

    def difference(self, *others: Iterable[T]) -> "FrozenOrderedSet[T]":
        return cast(FrozenOrderedSet[T], super().difference(*others))

    def symmetric_difference(self, *others: Iterable[T]) -> "FrozenOrderedSet[T]":
        return cast(FrozenOrderedSet[T], super().symmetric_difference(*others))

    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = 0
            for item in self._items.keys():
                self._hash ^= hash(item)
        return self._hash
