# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import LLVMCToolchain
from pants.backend.native.targets.native_library import CLibrary
from pants.backend.native.tasks.native_compile import NativeCompile
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf


class CCompile(NativeCompile):

  options_scope = 'c-compile'

  # Compile only C library targets.
  source_target_constraint = SubclassesOf(CLibrary)

  workunit_label = 'c-compile'

  @classmethod
  def implementation_version(cls):
    return super(CCompile, cls).implementation_version() + [('CCompile', 0)]

  @memoized_property
  def _c_toolchain(self):
    return self._request_single(LLVMCToolchain, self._native_toolchain).c_toolchain

  def get_compiler(self):
    return self._c_toolchain.c_compiler
