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

  def test_empty_products(self):
    c = self.make_target('c')
    self.assertFalse(self.products.get_for_target(c))

  def test_non_empty_products(self):
    c = self.make_target('c')
    self.products.add_for_target(c, [3])
    self.assertTrue(self.products.get_for_target(c))

  def test_dfs_get(self):
    c = self.make_target('c')
    b = self.make_target('b', dependencies=[c])
    a = self.make_target('a', dependencies=[b, c])
    self.products.add_for_target(a, [1])
    self.products.add_for_target(b, [2])
    self.products.add_for_target(c, [3])

    self.assertEquals(self.products.get_for_target_dfs(a), OrderedSet([3, 2, 1]))
    self.assertEquals(self.products.get_for_target_dfs(b), OrderedSet([3, 2]))
    self.assertEquals(self.products.get_for_target_dfs(c), OrderedSet([3]))

  def test_dfs_get_with_filtering(self):
    c = self.make_target('c')
    b = self.make_target('b', tags=['odd'], dependencies=[c])
    a = self.make_target('a', dependencies=[b, c])
    self.products.add_for_target(a, [1])
    self.products.add_for_target(b, [2])
    self.products.add_for_target(c, [3, 4])

    def keep_odd(target, products):
      if 'odd' in target.tags:
        return [p for p in products if p % 2 != 0]
      else:
        return products
    self.assertEquals(self.products.get_for_target_dfs(a, filter_child_products=keep_odd),
                      OrderedSet([3, 2, 1]))
