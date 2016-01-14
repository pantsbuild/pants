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

    self.assertEquals(self.products.get_for_targets(a.closure(bfs=True)), OrderedSet([1, 2, 3]))
    self.assertEquals(self.products.get_for_targets(b.closure(bfs=True)), OrderedSet([2, 3]))
    self.assertEquals(self.products.get_for_targets(c.closure(bfs=True)), OrderedSet([3]))
    self.assertEquals(self.products.get_for_target(a), OrderedSet([1]))
    self.assertEquals(self.products.get_for_target(b), OrderedSet([2]))
    self.assertEquals(self.products.get_for_target(c), OrderedSet([3]))

  def test_get_product_target_mappings_for_targets(self):
    b = self.make_target('b')
    a = self.make_target('a', dependencies=[b])
    self.products.add_for_target(a, [1, 3])
    self.products.add_for_target(b, [2, 3])

    self.assertEquals(self.products.get_for_targets(a.closure(bfs=True)), OrderedSet([1, 3, 2]))
    self.assertEquals(self.products.get_for_targets(b.closure(bfs=True)), OrderedSet([2, 3]))

    self.assertEquals(self.products.get_product_target_mappings_for_targets(a.closure(bfs=True)),
                      [(1, a), (3, a), (2, b), (3, b)])

  def test_copy(self):
    c = self.make_target('c')
    b = self.make_target('b', dependencies=[c])
    a = self.make_target('a', dependencies=[b, c])
    self.products.add_for_target(a, [1])
    self.products.add_for_target(b, [2])

    copied = self.products.copy()

    self.assertEquals(self.products.get_for_targets(a.closure(bfs=True)), OrderedSet([1, 2]))
    self.assertEquals(self.products.get_for_targets(b.closure(bfs=True)), OrderedSet([2]))
    self.assertEquals(copied.get_for_targets(a.closure(bfs=True)), OrderedSet([1, 2]))
    self.assertEquals(copied.get_for_targets(b.closure(bfs=True)), OrderedSet([2]))

    copied.add_for_target(c, [3])

    self.assertEquals(self.products.get_for_targets(a.closure(bfs=True)), OrderedSet([1, 2]))
    self.assertEquals(self.products.get_for_targets(b.closure(bfs=True)), OrderedSet([2]))
    self.assertEquals(self.products.get_for_targets(c.closure(bfs=True)), OrderedSet())
    self.assertEquals(copied.get_for_targets(a.closure(bfs=True)), OrderedSet([1, 2, 3]))
    self.assertEquals(copied.get_for_targets(b.closure(bfs=True)), OrderedSet([2, 3]))
    self.assertEquals(copied.get_for_targets(c.closure(bfs=True)), OrderedSet([3]))

  def test_remove_for_target(self):
    c = self.make_target('c')
    b = self.make_target('b', dependencies=[c])
    a = self.make_target('a', dependencies=[b, c])
    self.products.add_for_target(a, [1])
    self.products.add_for_target(b, [2])
    self.products.add_for_target(c, [3])

    self.products.remove_for_target(a, [1])

    self.assertEquals(self.products.get_for_targets(a.closure(bfs=True)), OrderedSet([2, 3]))
    self.assertEquals(self.products.get_for_targets(b.closure(bfs=True)), OrderedSet([2, 3]))
    self.assertEquals(self.products.get_for_targets(c.closure(bfs=True)), OrderedSet([3]))

  def test_empty_products(self):
    c = self.make_target('c')
    self.assertFalse(self.products.get_for_target(c))

  def test_non_empty_products(self):
    c = self.make_target('c')
    self.products.add_for_target(c, [3])
    self.assertTrue(self.products.get_for_target(c))

  def test_target_for_product_existing_product(self):
    c = self.make_target('c')
    self.products.add_for_target(c, [3])

    found_target = self.products.target_for_product(3)

    self.assertEqual(c, found_target)

  def test_target_for_product_nonexistent_product(self):
    c = self.make_target('c')
    self.products.add_for_target(c, [3])

    found_target = self.products.target_for_product(1000)

    self.assertIsNone(found_target)
