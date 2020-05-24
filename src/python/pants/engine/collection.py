# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, ClassVar, Iterable, Sequence, TypeVar, Union, overload

from pants.util.ordered_set import FrozenOrderedSet

T = TypeVar("T")


class Collection(Sequence[T]):
    """A light newtype around immutable sequences for use with the V2 engine.

    This should be subclassed when you want to create a distinct collection type, such as:

        @dataclass(frozen=True)
        class Example:
            val1: str

        class Examples(Collection[Example]):
            pass
    """

    def __init__(self, dependencies: Iterable[T] = ()) -> None:
        # TODO: rename to `items`, `elements`, or even make this private. Python consumers should
        #  not directly access this.
        self.dependencies = tuple(dependencies)

    @overload  # noqa: F811
    def __getitem__(self, index: int) -> T:
        ...

    @overload  # noqa: F811
    def __getitem__(self, index: slice) -> "Collection[T]":
        ...

    def __getitem__(self, index: Union[int, slice]) -> Union[T, "Collection[T]"]:  # noqa: F811
        if isinstance(index, int):
            return self.dependencies[index]
        return self.__class__(self.dependencies[index])

    def __len__(self) -> int:
        return len(self.dependencies)

    def __eq__(self, other: Union[Any, "Collection"]) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.dependencies == other.dependencies

    def __hash__(self) -> int:
        return hash(self.dependencies)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({list(self.dependencies)})"


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
        super().__init__(iterable if not self.sort_input else sorted(iterable))

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({list(self._items)})"
