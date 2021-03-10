# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, ClassVar, Iterable, Tuple, TypeVar, cast, overload

from pants.util.ordered_set import FrozenOrderedSet

T = TypeVar("T")


class Collection(Tuple[T, ...]):
    """A light newtype around immutable sequences for use with the V2 engine.

    This should be subclassed when you want to create a distinct collection type, such as:

        @dataclass(frozen=True)
        class Example:
            val1: str

        class Examples(Collection[Example]):
            pass

    N.B: Collection instances are only considered equal if both their types and contents are equal.
    """

    @overload  # noqa: F811
    def __getitem__(self, index: int) -> T:
        ...

    @overload  # noqa: F811
    def __getitem__(self, index: slice) -> Collection[T]:
        ...

    def __getitem__(self, index: int | slice) -> T | Collection[T]:  # noqa: F811
        result = super().__getitem__(index)
        if isinstance(index, int):
            return cast(T, result)
        return self.__class__(cast(Tuple[T, ...], result))

    def __eq__(self, other: Any) -> bool:
        return type(self) == type(other) and super().__eq__(other)

    def __ne__(self, other: Any) -> bool:
        # We must explicitly override to provide the inverse of _our_ __eq__ and not get the
        # inverse of tuple.__eq__.
        return not self == other

    # Unlike in Python 2 we must explicitly implement __hash__ since we explicitly implement __eq__
    # per the Python 3 data model.
    # See: https://docs.python.org/3/reference/datamodel.html#object.__hash__
    __hash__ = Tuple.__hash__

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({list(self)})"


# NB: This name is clunky. It would be more appropriate to call it `Set`, but that is claimed by
#  `typing.Set` already. See
#  https://github.com/pantsbuild/pants/pull/9590#pullrequestreview-395970440.
class DeduplicatedCollection(FrozenOrderedSet[T]):
    """A light newtype around FrozenOrderedSet for use with the V2 engine.

    This should be subclassed when you want to create a distinct collection type, such as:

        @dataclass(frozen=True)
        class Example:
            val1: str

        class Examples(DeduplicatedCollection[Example]):
            pass

    If it is safe to sort the inputs, you should do so for more cache hits by setting the class
    property `sort_input = True`.
    """

    sort_input: ClassVar[bool] = False

    def __init__(self, iterable: Iterable[T] = ()) -> None:
        super().__init__(
            iterable if not self.sort_input else sorted(iterable)  # type: ignore[type-var]
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({list(self._items)})"
