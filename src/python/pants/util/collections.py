# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections
import collections.abc
from typing import Any, Iterable, List, MutableMapping, TypeVar


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
    it = iter(iterable)
    first_item = next(it)

    try:
        next(it)
    except StopIteration:
        return first_item

    raise ValueError(f"iterable {iterable!r} has more than one element.")


def ensure_list(
    val: Any | Iterable[Any], *, expected_type: type[_T], allow_single_scalar: bool = False
) -> list[_T]:
    """Ensure that every element of an iterable is the expected type and convert the result to a
    list.

    If `allow_single_scalar` is True, a single value T will be wrapped into a `List[T]`.
    """
    if isinstance(val, expected_type):
        if not allow_single_scalar:
            raise ValueError(f"The value {val} must be wrapped in an iterable (e.g. a list).")
        return [val]
    if not isinstance(val, collections.abc.Iterable):
        raise ValueError(
            f"The value {val} (type {type(val)}) was not an iterable of {expected_type}."
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


def ensure_str_list(val: str | Iterable[str], *, allow_single_str: bool = False) -> list[str]:
    """Ensure that every element of an iterable is a string and convert the result to a list.

    If `allow_single_str` is True, a single `str` will be wrapped into a `List[str]`.
    """
    return ensure_list(val, expected_type=str, allow_single_scalar=allow_single_str)
