# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.iterators import accumulate


class AccumulateTest(unittest.TestCase):
  def test_empty(self):
    self.assertEqual([], list(accumulate(())))

  def test_single(self):
    self.assertEqual([42], list(accumulate((42,))))

  def test_nominal(self):
    self.assertEqual([1, 2, 3], list(accumulate((1, 1, 1))))

  def test_heterogeneous(self):
    self.assertEqual([1, '11', '111'], list(accumulate((1, 1, 1),
                                                       func=lambda x, y: str(x) + str(y))))
