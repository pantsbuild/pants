# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections
import collections.abc
import gc
import math
from sys import getsizeof
from typing import Any, Callable, Iterable, Iterator, MutableMapping, TypeVar

from pants.engine.internals import native_engine
from pants.util.strutil import softwrap


def recursively_update(d: MutableMapping, d2: MutableMapping) -> None:
    """dict.update but which merges child dicts (dict2 takes precedence where there's conflict)."""
    for k, v in d2.items():
        if k in d:
            if isinstance(v, dict):
                recursively_update(d[k], v)
                continue
        d[k] = v


def deep_getsizeof(o: Any, ids: set[int]) -> int:
    """Find the memory footprint of the given object.

    To avoid double-counting, `ids` should be a set of object ids which have been visited by
    previous calls to this method.
    """
    if id(o) in ids:
        return 0

    d = deep_getsizeof
    r = getsizeof(o)
    ids.add(id(o))

    return r + sum(d(x, ids) for x in gc.get_referents())


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
                softwrap(
                    f"""
                    Not all elements of the iterable have type {expected_type}. Encountered the
                    element {x} of type {type(x)} at index {i}.
                    """
                )
            )
        result.append(x)
    return result


def ensure_str_list(val: str | Iterable[str], *, allow_single_str: bool = False) -> list[str]:
    """Ensure that every element of an iterable is a string and convert the result to a list.

    If `allow_single_str` is True, a single `str` will be wrapped into a `List[str]`.
    """
    return ensure_list(val, expected_type=str, allow_single_scalar=allow_single_str)


def partition_sequentially(
    items: Iterable[_T],
    *,
    key: Callable[[_T], str],
    size_target: int,
    size_max: int | None = None,
) -> Iterator[list[_T]]:
    """Stably partitions the given items into batches of around `size_target` items.

    The "stability" property refers to avoiding adjusting all batches when a single item is added,
    which could happen if the items were trivially windowed using `itertools.islice` and an
    item was added near the front of the list.

    Batches will optionally be capped to `size_max`, but note that this can weaken the stability
    properties of the bucketing, by forcing bucket boundaries to be created where they otherwise
    might not.
    """

    # To stably partition the arguments into ranges of approximately `size_target`, we sort them,
    # and create a new batch sequentially once we encounter an item hash prefixed with a threshold
    # of zeros.
    #
    # The hashes act like a (deterministic) series of rolls of an evenly distributed die. The
    # probability of a hash prefixed with Z zero bits is 1/2^Z, and so to break after N items on
    # average, we look for `Z == log2(N)` zero bits.
    #
    # Breaking on these deterministic boundaries reduces the chance that adding or removing items
    # causes multiple buckets to be recalculated. But when a `size_max` value is set, it's possible
    # for adding items to cause multiple sequential buckets to be affected.
    zero_prefix_threshold = math.log(max(1, size_target), 2)

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
        prefix_zero_bits = native_engine.hash_prefix_zero_bits(item_key)
        if prefix_zero_bits >= zero_prefix_threshold or (size_max and len(batch) >= size_max):
            yield emit_batch()
    if batch:
        yield emit_batch()
