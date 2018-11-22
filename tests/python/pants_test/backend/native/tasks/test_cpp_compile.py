# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from textwrap import dedent

from pants.backend.native.targets.native_library import CppLibrary
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants_test.backend.native.tasks.native_task_test_base import (NativeCompileTestMixin,
                                                                   NativeTaskTestBase)


class CppCompileTest(NativeTaskTestBase, NativeCompileTestMixin):
  @classmethod
  def task_type(cls):
    return CppCompile

  def create_simple_header_only_library(self, **kwargs):
    self.create_file('src/cpp/test/test.hpp', contents=dedent("""
      #ifndef __TEST_HPP__
      #define __TEST_HPP__

      template <typename T>
      T add(T a, T b) {
        return a + b;
      }

      #endif
"""))
    return self.make_target(spec='src/cpp/test',
                     target_type=CppLibrary,
                     sources=['test.hpp'],
                     **kwargs)

  def test_header_only_target_noop(self):
    cpp = self.create_simple_header_only_library()
    context = self.prepare_context_for_compile(target_roots=[cpp])
    cpp_compile = self.create_task(context)

    with self.captured_logging(level=logging.INFO) as logs:
      cpp_compile.execute()
      info = list(logs.infos())[-1]
      self.assertIn('is a header-only library', info)

  def test_caching(self):
    cpp = self.create_simple_cpp_library()
    context = self.prepare_context_for_compile(target_roots=[cpp])
    cpp_compile = self.create_task(context)

    cpp_compile.execute()
    cpp_compile.execute()
