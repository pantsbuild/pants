# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class TestBundleCreate(JvmToolTaskTestBase):

  @classmethod
  def task_type(cls):
    return BundleCreate

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm())

  def test_jvm_bundle_products(self):
    self.add_to_build_file('foo', dedent("""
      jvm_binary(
        name='foo-binary',
        source='Foo.java',
      )
      jvm_app(
        name='foo-app',
        basename='FooApp',
        dependencies=[
          ':foo-binary',
        ]
      )
    """))
    app_target = self.target('//foo:foo-app')
    context = self.context(target_roots=[app_target])
    with self.add_data(context.products, 'classes_by_target', app_target, 'Foo.class'):
      with self.add_data(context.products, 'resources_by_target', app_target, 'foo.txt'):
        self.execute(context)
        products = context.products.get('jvm_bundles')
        self.assertIsNotNone(products)
        product_data = products.get(app_target)
        self.assertEquals({os.path.join(self.build_root, 'dist'): ['FooApp-bundle']},
                          product_data)
