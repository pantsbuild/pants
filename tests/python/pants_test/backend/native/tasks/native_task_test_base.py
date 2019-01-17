# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from pants.backend.native import register
from pants.backend.native.targets.native_library import CppLibrary
from pants.backend.native.tasks.conan_fetch import ConanFetch
from pants_test.task_test_base import TaskTestBase


class NativeTaskTestBase(TaskTestBase):
  @classmethod
  def rules(cls):
    return super(NativeTaskTestBase, cls).rules() + register.rules()


class NativeCompileTestMixin(object):

  def _retrieve_single_product_at_target_base(self, product_mapping, target):
    product = product_mapping.get(target)
    base_dirs = list(product.keys())
    self.assertEqual(1, len(base_dirs))
    single_base_dir = base_dirs[0]
    all_products = product[single_base_dir]
    self.assertEqual(1, len(all_products))
    single_product = all_products[0]
    return single_product

  def create_simple_cpp_library(self, **kwargs):
    self.create_file('src/cpp/test/test.hpp', contents=dedent("""
      #ifndef __TEST_HPP__
      #define __TEST_HPP__

      int test(int);

      extern "C" int test_exported(int);

      #endif
    """))
    self.create_file('src/cpp/test/test.cpp', contents=dedent("""
      #include "test.hpp"

      int test(int x) {
        return x / 137;
      }

      extern "C" int test_exported(int x) {
        return test(x * 42);
      }
    """))
    return self.make_target(spec='src/cpp/test',
                            target_type=CppLibrary,
                            sources=['test.hpp', 'test.cpp'],
                            **kwargs)

  def prepare_context_for_compile(self, target_roots, for_task_types=None, **kwargs):
    native_elf_fetch_task_type = self.synthesize_task_subtype(ConanFetch,
                                                              'native_elf_fetch_scope')

    for_task_types = list(for_task_types or ()) + [native_elf_fetch_task_type]
    context = self.context(target_roots=target_roots, for_task_types=for_task_types, **kwargs)

    native_elf_fetch = native_elf_fetch_task_type(context,
                                                  os.path.join(self.pants_workdir,
                                                               'native_elf_fetch'))
    native_elf_fetch.execute()
    return context
