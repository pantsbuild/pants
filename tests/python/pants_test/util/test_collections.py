# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from functools import partial
from typing import List

import pytest

from pants.util.collections import (
    assert_single_element,
    ensure_list,
    ensure_str_list,
    factory_dict,
    recursively_update,
)


class TestCollections(unittest.TestCase):
    def test_factory_dict(self) -> None:
        def make_default_value(x: int) -> List[int]:
            return [x ** 3]

        cubes = factory_dict(make_default_value, ((x, x ** 2) for x in range(3)), three=42)

        # Check kwargs passed to the constructor
        self.assertEqual(42, cubes["three"])

        # Check args passed to the constructor
        self.assertEqual(0, cubes[0])
        self.assertEqual(1, cubes[1])
        self.assertEqual(4, cubes[2])

        # Check value factory for missing values
        self.assertEqual([27], cubes[3])

        # Check value factory only used for __getitem__, not other methods like get()
        self.assertIsNone(cubes.get(4))
        self.assertEqual("jake", cubes.get(5, "jake"))

        # This time we access directly via __getitem__
        self.assertEqual([64], cubes[4])
        cubes.get(4).append(8)  # type: ignore[union-attr]
        self.assertEqual([64, 8], cubes[4])

    def test_recursively_update(self) -> None:
        d1 = {"a": 1, "b": {"c": 2, "o": "z"}, "z": {"y": 0}}
        d2 = {"e": 3, "b": {"f": 4, "o": 9}, "g": {"h": 5}, "z": 7}
        recursively_update(d1, d2)
        self.assertEqual(d1, {"a": 1, "b": {"c": 2, "f": 4, "o": 9}, "e": 3, "g": {"h": 5}, "z": 7})

    def test_assert_single_element(self) -> None:
        single_element = [1]
        self.assertEqual(1, assert_single_element(single_element))

        no_elements: List[int] = []
        with self.assertRaises(StopIteration):
            assert_single_element(no_elements)

        too_many_elements = [1, 2]
        with self.assertRaises(ValueError) as cm:
            assert_single_element(too_many_elements)
        expected_msg = "iterable [1, 2] has more than one element."
        self.assertEqual(expected_msg, str(cm.exception))

    def test_ensure_list(self) -> None:
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

    def test_ensure_str_list(self) -> None:
        assert ensure_str_list(("hello", "there")) == ["hello", "there"]

        assert ensure_str_list("hello", allow_single_str=True) == ["hello"]
        with pytest.raises(ValueError):
            ensure_str_list("hello")

        with pytest.raises(ValueError):
            ensure_str_list(0)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ensure_str_list([0, 1])  # type: ignore[list-item]
