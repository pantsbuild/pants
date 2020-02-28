# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from typing import List

from pants.util.collections import assert_single_element, factory_dict, recursively_update


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
        d1 = {"a": 1, "b": {"c": 2, "o": "z",}, "z": {"y": 0,}}
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
