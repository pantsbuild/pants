# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from textwrap import dedent

from pants.backend.native.targets.native_library import CLibrary
from pants.backend.native.tasks.c_compile import CCompile
from pants_test.backend.native.tasks.native_task_test_base import (NativeCompileTestMixin,
                                                                   NativeTaskTestBase)


class CCompileTest(NativeTaskTestBase, NativeCompileTestMixin):
  @classmethod
  def task_type(cls):
    return CCompile

  def create_simple_c_library(self, **kwargs):
    self.create_file('src/c/test/test.h', contents=dedent("""
      #ifndef __TEST_H__
      #define __TEST_H__

      int test(int);

      #endif
    """))
    self.create_file('src/c/test/test.c', contents=dedent("""
      #include "test.h"

      int test(int x) {
        return x / 137;
      }
    """))
    return self.make_target(spec='src/c/test',
                            target_type=CLibrary,
                            sources=['test.h', 'test.c'],
                            **kwargs)

  def test_caching(self):
    c = self.create_simple_c_library()
    context = self.prepare_context_for_compile(target_roots=[c])
    c_compile = self.create_task(context)

    c_compile.execute()
    c_compile.execute()
