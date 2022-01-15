# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections
import collections.abc
import math
from typing import Any, Callable, Iterable, Iterator, MutableMapping, Sequence, TypeVar

from pants.engine.internals import native_engine


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
    result: list[_T] = []
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


def partition_sequentially(
    items: Sequence[_T],
    *,
    key: Callable[[_T], str],
    size_min: int,
    size_max: int | None = None,
) -> Iterator[list[_T]]:
    """Stably partitions the given items into batches of at least size_min.

    The "stability" property refers to avoiding adjusting all batches when a single item is added,
    which could happen if the items were trivially windowed using `itertools.islice` and an
    item was added near the front of the list.

    Batches will be capped to `size_max`, which defaults `size_min*2`.
    """

    # To stably partition the arguments into ranges of at least `size_min`, we sort them, and
    # create a new batch sequentially once we have the minimum number of entries, _and_ we encounter
    # an item hash prefixed with a threshold of zeros.
    zero_prefix_threshold = math.log(size_min // 8, 2)
    size_max = size_min * 2 if size_max is None else size_max

    batch: list[_T] = []

    def emit_batch() -> list[_T]:
        assert batch
        result = list(batch)
        batch.clear()
        return result

    keyed_items = []
    for item in items:
        keyed_items.append((key(item), item))
    keyed_items.sort()

    for item_key, item in keyed_items:
        batch.append(item)
        if (
            len(batch) >= size_min
            and native_engine.hash_prefix_zero_bits(item_key) >= zero_prefix_threshold
        ) or (len(batch) >= size_max):
            yield emit_batch()
    if batch:
        yield emit_batch()
