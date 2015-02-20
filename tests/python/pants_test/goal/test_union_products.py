# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import OrderedSet

from pants.goal.products import UnionProducts
from pants_test.base_test import BaseTest


class UnionProductsTest(BaseTest):
  def setUp(self):
    super(UnionProductsTest, self).setUp()
    self.products = UnionProducts()

  def test_get_for_target(self):
    c = self.make_target('c')
    b = self.make_target('b', dependencies=[c])
    a = self.make_target('a', dependencies=[b, c])
    self.products.add_for_target(a, [1])
    self.products.add_for_target(b, [2])
    self.products.add_for_target(c, [3])

    self.assertEquals(self.products.get_for_target(a), OrderedSet([1, 2, 3]))
    self.assertEquals(self.products.get_for_target(b), OrderedSet([2, 3]))
    self.assertEquals(self.products.get_for_target(c), OrderedSet([3]))
