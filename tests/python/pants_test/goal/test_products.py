# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.goal.products import Products


class ProductsTest(unittest.TestCase):
  def setUp(self):
    self.products = Products()

  def test_require(self):
    self.products.require('foo')

    predicate = self.products.isrequired('foo')
    self.assertIsNotNone(predicate)
    self.assertFalse(predicate(42))

    self.assertIsNone(self.products.isrequired('bar'))

    # require should not cross-contaminate require_data
    self.assertFalse(self.products.is_required_data('foo'))
    self.assertFalse(self.products.is_required_data('bar'))

  def test_require_predicate(self):
    self.products.require('foo', predicate=lambda x: x == 42)

    predicate = self.products.isrequired('foo')
    self.assertIsNotNone(predicate)
    self.assertTrue(predicate(42))
    self.assertFalse(predicate(0))

  def test_require_multiple_predicates(self):
    self.products.require('foo', predicate=lambda x: x == 1)
    self.products.require('foo', predicate=lambda x: x == 2)
    self.products.require('foo', predicate=lambda x: x == 3)

    predicate = self.products.isrequired('foo')
    self.assertIsNotNone(predicate)
    self.assertFalse(predicate(0))
    self.assertTrue(predicate(1))
    self.assertTrue(predicate(2))
    self.assertTrue(predicate(3))
    self.assertFalse(predicate(4))

  def test_get(self):
    foo_product_mapping1 = self.products.get('foo')
    foo_product_mapping2 = self.products.get('foo')

    self.assertIsInstance(foo_product_mapping1, Products.ProductMapping)
    self.assertIs(foo_product_mapping1, foo_product_mapping2)

  def test_get_does_not_require(self):
    self.assertIsNone(self.products.isrequired('foo'))
    self.products.get('foo')
    self.assertIsNone(self.products.isrequired('foo'))
    self.products.require('foo')
    self.assertIsNotNone(self.products.isrequired('foo'))

  def test_require_data(self):
    self.products.require_data('foo')

    self.assertTrue(self.products.is_required_data('foo'))
    self.assertFalse(self.products.is_required_data('bar'))

    # require_data should not cross-contaminate require
    self.assertIsNone(self.products.isrequired('foo'))
    self.assertIsNone(self.products.isrequired('bar'))

  def test_get_data(self):
    self.assertIsNone(self.products.get_data('foo'))

    data1 = self.products.get_data('foo', dict)
    data2 = self.products.get_data('foo', dict)

    self.assertIsInstance(data1, dict)
    self.assertIs(data1, data2)

  def test_get_data_does_not_require_data(self):
    self.assertFalse(self.products.is_required_data('foo'))
    self.products.get_data('foo')
    self.assertFalse(self.products.is_required_data('foo'))
    self.products.require_data('foo')
    self.assertTrue(self.products.is_required_data('foo'))
