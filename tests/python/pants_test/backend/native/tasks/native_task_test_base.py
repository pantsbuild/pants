# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from pants.backend.native import register
from pants.backend.native.targets.native_library import CppLibrary
from pants.backend.native.tasks.native_external_library_fetch import NativeExternalLibraryFetch
from pants_test.task_test_base import TaskTestBase


class NativeTaskTestBase(TaskTestBase):
  @classmethod
  def rules(cls):
    return super(NativeTaskTestBase, cls).rules() + register.rules()


class NativeCompileTestMixin(object):
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
    native_elf_fetch_task_type = self.synthesize_task_subtype(NativeExternalLibraryFetch,
                                                              'native_elf_fetch_scope')

    for_task_types = list(for_task_types or ()) + [native_elf_fetch_task_type]
    context = self.context(target_roots=target_roots, for_task_types=for_task_types, **kwargs)

    native_elf_fetch = native_elf_fetch_task_type(context,
                                                  os.path.join(self.pants_workdir,
                                                               'native_elf_fetch'))
    native_elf_fetch.execute()
    return context
