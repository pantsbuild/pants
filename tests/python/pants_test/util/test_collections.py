# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.collections import combined_dict, recursively_update


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

  def test_recursively_update(self):
    d = {'a': 1, 'b': {'c': 2, 'o': 'z'}}
    recursively_update(d, {'e': 3, 'b': {'f': 4, 'o': 9}, 'g': {'h': 5}})
    self.assertEqual(
      d, {'a': 1, 'b': {'c': 2, 'f': 4, 'o': 9}, 'e': 3, 'g': {'h': 5}}
    )
