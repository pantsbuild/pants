# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar, Iterable, TypeVar

from pants.engine.internals.native_engine import Collection as Collection  # noqa: F401
from pants.util.ordered_set import FrozenOrderedSet

T = TypeVar("T")


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
