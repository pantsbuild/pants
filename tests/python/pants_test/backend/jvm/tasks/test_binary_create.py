# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class TestBinaryCreate(JvmToolTaskTestBase):

  @classmethod
  def task_type(cls):
    return BinaryCreate

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm())

  def test_jvm_binaries_products(self):
    self.add_to_build_file('foo', dedent("""
      jvm_binary(
        name='foo-binary',
        source='Foo.java',
      )
    """))
    binary_target = self.target('//foo:foo-binary')
    context = self.context(target_roots=[binary_target])
    with self.add_data(context.products, 'classes_by_target', binary_target, 'Foo.class'):
      with self.add_data(context.products, 'resources_by_target', binary_target, 'foo.txt'):
        self.execute(context)
        jvm_binary_products = context.products.get('jvm_binaries')
        self.assertIsNotNone(jvm_binary_products)
        product_data = jvm_binary_products.get(binary_target)
        self.assertEquals({os.path.join(self.build_root, 'dist') : ['foo-binary.jar']},
                          product_data)
