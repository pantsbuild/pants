# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.tasks.cpp_compile import CppCompile
from pants_test.backend.native.tasks.native_task_test_base import (NativeCompileTestMixin,
                                                                   NativeTaskTestBase)


class CppCompileTest(NativeTaskTestBase, NativeCompileTestMixin):
  @classmethod
  def task_type(cls):
    return CppCompile

  def test_caching(self):
    cpp = self.create_simple_cpp_library()
    context = self.prepare_context_for_compile(target_roots=[cpp])
    cpp_compile = self.create_task(context)

    cpp_compile.execute()
    cpp_compile.execute()
