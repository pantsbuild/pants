# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections
import collections.abc
from typing import Any, Callable, DefaultDict, Iterable, List, MutableMapping, Type, TypeVar, Union

_K = TypeVar("_K")
_V = TypeVar("_V")


def factory_dict(value_factory: Callable[[_K], _V], *args, **kwargs) -> DefaultDict:
    """A dict whose values are computed by `value_factory` when a `__getitem__` key is missing.

    Note that values retrieved by any other method will not be lazily computed; eg: via `get`.

    :param value_factory:
    :param *args: Any positional args to pass through to `dict`.
    :param **kwrags: Any kwargs to pass through to `dict`.
    """

    class FactoryDict(collections.defaultdict):
        @staticmethod
        def __never_called():
            raise AssertionError(
                "The default factory should never be called since we override " "__missing__."
            )

        def __init__(self):
            super().__init__(self.__never_called, *args, **kwargs)

        def __missing__(self, key):
            value = value_factory(key)
            self[key] = value
            return value

    return FactoryDict()


def recursively_update(d: MutableMapping, d2: MutableMapping) -> None:
    """dict.update but which merges child dicts (dict2 takes precedence where there's conflict)."""
    for k, v in d2.items():
        if k in d:
            if isinstance(v, dict):
                recursively_update(d[k], v)
                continue
        d[k] = v


_T = TypeVar("_T")


def assert_single_element(iterable: Iterable[_T]) -> _T:
    """Get the single element of `iterable`, or raise an error.

    :raise: :class:`StopIteration` if there is no element.
    :raise: :class:`ValueError` if there is more than one element.
    """
    items = list(iterable)

    if len(items) == 1:
        return items[0]
    if len(items) == 0:
        raise StopIteration(f'iterable {iterable} had zero elements')
    raise ValueError(f"iterable {iterable} has more than one element (elements were: {items}).")


def ensure_list(val: Union[Any, Iterable[Any]], *, expected_type: Type[_T]) -> List[_T]:
    """Given either a single value or an iterable of values, always return a list.

    This performs runtime type checking to ensure that every element of the list is the expected
    type.
    """
    if isinstance(val, expected_type):
        return [val]
    if not isinstance(val, collections.abc.Iterable):
        raise ValueError(
            f"The value {val} (type {type(val)}) did not have the expected type {expected_type} "
            "nor was it an iterable."
        )
    result: List[_T] = []
    for i, x in enumerate(val):
        if not isinstance(x, expected_type):
            raise ValueError(
                f"Not all elements of the iterable have type {expected_type}. Encountered the "
                f"element {x} of type {type(x)} at index {i}."
            )
        result.append(x)
    return result


def ensure_str_list(val: Union[str, Iterable[str]]) -> List[str]:
    """Given either a single string or an iterable of strings, always return a list."""
    return ensure_list(val, expected_type=str)
