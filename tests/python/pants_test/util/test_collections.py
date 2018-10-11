# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest
from builtins import str

from pants.util.collections import (assert_single_element, combined_dict, factory_dict,
                                    recursively_update)


class TestCollections(unittest.TestCase):
  def test_combined_dict(self):
    self.assertEqual(
      combined_dict(
       {'a': 1, 'b': 1, 'c': 1},
       {'b': 2, 'c': 2},
       {'c': 3},
      ),
      {'a': 1, 'b': 2, 'c': 3}
    )

  def test_factory_dict(self):
    cubes = factory_dict(lambda x: x ** 3, ((x, x ** 2) for x in range(3)), three=42)
    self.assertEqual(0, cubes[0])
    self.assertEqual(1, cubes[1])
    self.assertEqual(4, cubes[2])

    self.assertEqual(27, cubes[3])

    self.assertIsNone(cubes.get(4))
    self.assertEqual(64, cubes[4])

    self.assertEqual(42, cubes['three'])

    self.assertEqual('jake', cubes.get(5, 'jake'))

  def test_recursively_update(self):
    d = {'a': 1, 'b': {'c': 2, 'o': 'z'}, 'z': {'y': 0}}
    recursively_update(d, {'e': 3, 'b': {'f': 4, 'o': 9}, 'g': {'h': 5}, 'z': 7})
    self.assertEqual(
      d, {'a': 1, 'b': {'c': 2, 'f': 4, 'o': 9}, 'e': 3, 'g': {'h': 5}, 'z': 7}
    )

  def test_assert_single_element(self):
    single_element = [1]
    self.assertEqual(1, assert_single_element(single_element))

    no_elements = []
    with self.assertRaises(StopIteration):
      assert_single_element(no_elements)

    too_many_elements = [1, 2]
    with self.assertRaises(ValueError) as cm:
      assert_single_element(too_many_elements)
    expected_msg = "iterable [1, 2] has more than one element."
    self.assertEqual(expected_msg, str(cm.exception))
