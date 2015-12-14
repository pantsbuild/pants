# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict
from contextlib import contextmanager

from pants.goal.products import MultipleRootedProducts, Products
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open
from pants_test.base_test import BaseTest


class ProductsTest(BaseTest):
  def setUp(self):
    super(ProductsTest, self).setUp()
    self.products = Products()

  def test_require(self):
    self.products.require('foo')

    self.assertTrue(self.products.isrequired('foo'))
    self.assertFalse(self.products.isrequired('bar'))

    # require should not cross-contaminate require_data
    self.assertFalse(self.products.is_required_data('foo'))
    self.assertFalse(self.products.is_required_data('bar'))

  def test_get(self):
    foo_product_mapping1 = self.products.get('foo')
    foo_product_mapping2 = self.products.get('foo')

    self.assertIsInstance(foo_product_mapping1, Products.ProductMapping)
    self.assertIs(foo_product_mapping1, foo_product_mapping2)

  def test_get_does_not_require(self):
    self.assertFalse(self.products.isrequired('foo'))
    self.products.get('foo')
    self.assertFalse(self.products.isrequired('foo'))
    self.products.require('foo')
    self.assertTrue(self.products.isrequired('foo'))

  def test_require_data(self):
    self.products.require_data('foo')

    self.assertTrue(self.products.is_required_data('foo'))
    self.assertFalse(self.products.is_required_data('bar'))

    # require_data should not cross-contaminate require
    self.assertFalse(self.products.isrequired('foo'))
    self.assertFalse(self.products.isrequired('bar'))

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

  def test_empty_products(self):
    foo_product_mapping = self.products.get('foo')
    self.assertFalse(foo_product_mapping)

  @contextmanager
  def add_products(self, context_products, product_type, target, *products):
    product_mapping = context_products.get(product_type)
    with temporary_dir() as outdir:
      def create_product(product):
        with safe_open(os.path.join(outdir, product), mode='w') as fp:
          fp.write(product)
        return product
      product_mapping.add(target, outdir, map(create_product, products))
      yield temporary_dir

  def test_non_empty_products(self):
    target = self.make_target('c')
    with self.add_products(self.products, 'foo', target, 'a.class'):
      foo_product_mapping = self.products.get('foo')
      self.assertTrue(foo_product_mapping)

  def test_empty_data(self):
    foo_product_mapping = self.products.get_data('foo')
    self.assertFalse(foo_product_mapping)

  @contextmanager
  def add_data(self, context_products, data_type, target, *products):
    make_products = lambda: defaultdict(MultipleRootedProducts)
    data_by_target = context_products.get_data(data_type, make_products)
    with temporary_dir() as outdir:
      def create_product(product):
        abspath = os.path.join(outdir, product)
        with safe_open(abspath, mode='w') as fp:
          fp.write(product)
        return abspath
      data_by_target[target].add_abs_paths(outdir, map(create_product, products))
      yield temporary_dir

  def test_non_empty_data(self):
    target = self.make_target('c')
    with self.add_data(self.products, 'foo', target, 'a.class'):
      foo_product_mapping = self.products.get_data('foo')
      self.assertTrue(foo_product_mapping)
