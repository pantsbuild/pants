# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class TestBundleCreate(JvmToolTaskTestBase):

  @classmethod
  def task_type(cls):
    return BundleCreate

  def test_jvm_bundle_products(self):
    binary_target = self.make_target(spec='//foo:foo-binary',
                                     target_type=JvmBinary,
                                     source='Foo.java')
    app_target = self.make_target(spec='//foo:foo-app',
                                  target_type=JvmApp,
                                  basename='FooApp',
                                  dependencies=[binary_target])
    context = self.context(target_roots=[app_target])
    context.products.safe_create_data('compile_classpath', init_func=ClasspathProducts)
    with self.add_data(context.products, 'classes_by_target', app_target, 'Foo.class'):
      with self.add_data(context.products, 'resources_by_target', app_target, 'foo.txt'):
        self.execute(context)
        products = context.products.get('jvm_bundles')
        self.assertIsNotNone(products)
        product_data = products.get(app_target)
        self.assertEquals({os.path.join(self.build_root, 'dist'): ['FooApp-bundle']},
                          product_data)
