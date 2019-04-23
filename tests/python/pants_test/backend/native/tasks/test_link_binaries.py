# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.targets.native_library import CppLibrary
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants.backend.native.tasks.link_object_files import LinkBinaries
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess
from pants_test.backend.native.tasks.native_task_test_base import (NativeCompileTestMixin,
                                                                   NativeTaskTestBase)


class LinkBinariesTest(NativeTaskTestBase, NativeCompileTestMixin):
  @classmethod
  def task_type(cls):
    return LinkBinaries

  def _create_simple_cpp_binary(self):
    self.create_file('src/cpp/test/test.cpp', contents=dedent("""
      #include <iostream>

      int main() {
        std::cout << "hello, world!" << std::endl;
      }
    """))
    return self.make_target(spec='src/cpp/test:main',
                            target_type=CppLibrary,
                            sources=['test.cpp'],
                            ctypes_native_library=NativeArtifact(exe_name='test'))

  def test_binary_creation(self):
    cpp_lib = self._create_simple_cpp_binary()

    cpp_compile_task_type = self.synthesize_task_subtype(CppCompile, 'cpp_compile_scope')

    with temporary_dir() as tmp_distdir:
      self.set_options(pants_distdir=tmp_distdir)

      context = self.prepare_context_for_compile(
        target_roots=[cpp_lib],
        for_task_types=[cpp_compile_task_type],
        options={
          'libc': {
            'enable_libc_search': True,
          },
        })

      cpp_compile = cpp_compile_task_type(context, os.path.join(self.pants_workdir, 'cpp_compile'))
      cpp_compile.execute()

      link_binaries = self.create_task(context)

      link_binaries.execute()

      output_binary_filename = assert_single_element(os.listdir(tmp_distdir))
      output = subprocess.check_output(['./{}'.format(output_binary_filename)],
                                       stderr=subprocess.STDOUT,
                                       cwd=tmp_distdir)
      self.assertEqual(output, b'hello, world!\n')
