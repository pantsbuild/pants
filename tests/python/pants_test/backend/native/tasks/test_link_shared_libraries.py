# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants.backend.native.tasks.link_shared_libraries import LinkSharedLibraries
from pants_test.backend.native.tasks.native_task_test_base import (NativeCompileTestMixin,
                                                                   NativeTaskTestBase)


class LinkSharedLibrariesTest(NativeTaskTestBase, NativeCompileTestMixin):
  @classmethod
  def task_type(cls):
    return LinkSharedLibraries

  def test_caching(self):
    cpp = self. create_simple_cpp_library(ctypes_native_library=NativeArtifact(lib_name='test'),)

    cpp_compile_task_type = self.synthesize_task_subtype(CppCompile, 'cpp_compile_scope')
    context = self.prepare_context_for_compile(target_roots=[cpp],
                                               for_task_types=[cpp_compile_task_type])

    cpp_compile = cpp_compile_task_type(context, os.path.join(self.pants_workdir, 'cpp_compile'))
    cpp_compile.execute()

    link_shared_libraries = self.create_task(context)

    link_shared_libraries.execute()
    link_shared_libraries.execute()
