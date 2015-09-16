# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class TestBinaryCreate(JvmToolTaskTestBase):

  @classmethod
  def task_type(cls):
    return BinaryCreate

  def test_jvm_binaries_products(self):
    binary_target = self.make_target(spec='//foo:foo-binary',
                                     target_type=JvmBinary,
                                     source='Foo.java')
    context = self.context(target_roots=[binary_target])
    context.products.safe_create_data('compile_classpath', init_func=ClasspathProducts)
    with self.add_data(context.products, 'classes_by_target', binary_target, 'Foo.class'):
      with self.add_data(context.products, 'resources_by_target', binary_target, 'foo.txt'):
        self.execute(context)
        jvm_binary_products = context.products.get('jvm_binaries')
        self.assertIsNotNone(jvm_binary_products)
        product_data = jvm_binary_products.get(binary_target)
        self.assertEquals({os.path.join(self.build_root, 'dist'): ['foo-binary.jar']},
                          product_data)
