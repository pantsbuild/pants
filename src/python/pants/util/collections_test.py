# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import annotations

from functools import partial

import pytest

from pants.util.collections import (
    assert_single_element,
    ensure_list,
    ensure_str_list,
    partition_sequentially,
    recursively_update,
)


def test_recursively_update() -> None:
    d1 = {"a": 1, "b": {"c": 2, "o": "z"}, "z": {"y": 0}}
    d2 = {"e": 3, "b": {"f": 4, "o": 9}, "g": {"h": 5}, "z": 7}
    recursively_update(d1, d2)
    assert d1 == {"a": 1, "b": {"c": 2, "f": 4, "o": 9}, "e": 3, "g": {"h": 5}, "z": 7}


def test_assert_single_element() -> None:
    single_element = [1]
    assert 1 == assert_single_element(single_element)

    no_elements: list[int] = []
    with pytest.raises(StopIteration):
        assert_single_element(no_elements)

    too_many_elements = [1, 2]
    with pytest.raises(ValueError) as cm:
        assert_single_element(too_many_elements)
    expected_msg = "iterable [1, 2] has more than one element."
    assert expected_msg == str(cm.value)


def test_ensure_list() -> None:
    # Reject single values by default, even if they're the expected type.
    with pytest.raises(ValueError):
        ensure_list(0, expected_type=int)
    with pytest.raises(ValueError):
        ensure_list(False, expected_type=bool)

    # Allow wrapping single values into a list.
    assert ensure_list(0, expected_type=int, allow_single_scalar=True) == [0]
    assert ensure_list(True, expected_type=bool, allow_single_scalar=True) == [True]
    arbitrary_object = object()
    assert ensure_list(arbitrary_object, expected_type=object, allow_single_scalar=True) == [
        arbitrary_object
    ]

    ensure_int_list = partial(ensure_list, expected_type=int)

    # Keep lists as lists
    assert ensure_int_list([]) == []
    assert ensure_int_list([0]) == [0]
    assert ensure_int_list([0, 1, 2]) == [0, 1, 2]

    # Convert other iterable types to a list
    assert ensure_int_list((0,)) == [0]
    assert ensure_int_list({0}) == [0]
    assert ensure_int_list({0: "hello"}) == [0]

    # Perform runtime type checks
    with pytest.raises(ValueError):
        ensure_int_list(["bad"])
    with pytest.raises(ValueError):
        ensure_int_list([0.0])
    with pytest.raises(ValueError):
        ensure_int_list([0, 1, "sneaky", 2, 3])


def test_ensure_str_list() -> None:
    assert ensure_str_list(("hello", "there")) == ["hello", "there"]

    assert ensure_str_list("hello", allow_single_str=True) == ["hello"]
    with pytest.raises(ValueError):
        ensure_str_list("hello")

    with pytest.raises(ValueError):
        ensure_str_list(0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ensure_str_list([0, 1])  # type: ignore[list-item]


@pytest.mark.parametrize("size_target", [0, 1, 8, 16, 32, 64, 128])
def test_partition_sequentially(size_target: int) -> None:
    # Adding an item at any position in the input sequence should affect either 1 or 2 (if the added
    # item becomes a boundary) buckets in the output.

    def partitioned_buckets(items: list[str]) -> set[tuple[str, ...]]:
        return {tuple(p) for p in partition_sequentially(items, key=str, size_target=size_target)}

    # We start with base items containing every other element from a sorted sequence.
    all_items = sorted(f"item{i}" for i in range(0, 1024))
    base_items = [item for i, item in enumerate(all_items) if i % 2 == 0]
    base_partitions = partitioned_buckets(base_items)

    # Then test that adding any of the remaining items (which will be interspersed in the base
    # items) only affects 1 or 2 buckets in the output (representing between a 1 and 4 delta
    # in the `^`/symmetric_difference between before and after).
    for to_add in [item for i, item in enumerate(all_items) if i % 2 == 1]:
        updated_partitions = partitioned_buckets([to_add, *base_items])
        assert 1 <= len(base_partitions ^ updated_partitions) <= 4
