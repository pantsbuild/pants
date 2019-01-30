# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from textwrap import dedent

from pants.backend.native.targets.native_library import CppLibrary, NativeLibrary
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants.backend.native.tasks.native_compile import ObjectFiles
from pants_test.backend.native.tasks.native_task_test_base import (NativeCompileTestMixin,
                                                                   NativeTaskTestBase)


class CppCompileTest(NativeTaskTestBase, NativeCompileTestMixin):
  @classmethod
  def task_type(cls):
    return CppCompile

  def create_simple_header_only_library(self, **kwargs):
    # TODO: determine if there are other features that people expect from header-only libraries that
    # we could be testing here. Currently this file's contents are just C++ which doesn't define any
    # non-template classes or methods.
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

    # Test that the task runs without error if provided a header-only library.
    cpp_compile = self.create_task(context)
    cpp_compile.execute()

    object_files_product = context.products.get(ObjectFiles)
    object_files_for_target = self._retrieve_single_product_at_target_base(object_files_product, cpp)
    # Test that no object files were produced.
    self.assertEqual(0, len(object_files_for_target.filenames))

  def test_caching(self):
    cpp = self.create_simple_cpp_library()
    context = self.prepare_context_for_compile(target_roots=[cpp])
    cpp_compile = self.create_task(context)

    # TODO: what is this testing?
    cpp_compile.execute()
    cpp_compile.execute()

  def test_target_level_toolchain_variant_llvm(self):
    self.set_options_for_scope('native-build-step', toolchain_variant='gnu')
    cpp_lib_target = self.make_target(
      '//:cpp_library',
      NativeLibrary,
      toolchain_variant='llvm'
    )

    task = self.create_task(self.context(target_roots=[cpp_lib_target]))
    compiler = task.get_compiler(cpp_lib_target)
    self.assertIn('llvm', compiler.path_entries[0])

  def test_target_level_toolchain_variant_default_llvm(self):
    self.set_options_for_scope('native-build-step', toolchain_variant='llvm')
    cpp_lib_target = self.make_target(
      '//:cpp_library',
      NativeLibrary,
    )

    task = self.create_task(self.context(target_roots=[cpp_lib_target]))
    compiler = task.get_compiler(cpp_lib_target)
    self.assertIn('llvm', compiler.path_entries[0])

  def test_target_level_toolchain_variant_default_gnu(self):
    self.set_options_for_scope('native-build-step', toolchain_variant='gnu')
    cpp_lib_target = self.make_target(
      '//:cpp_library',
      NativeLibrary,
    )

    task = self.create_task(self.context(target_roots=[cpp_lib_target]))
    compiler = task.get_compiler(cpp_lib_target)
    self.assertIn('gcc', compiler.path_entries[0])