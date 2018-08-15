# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import LLVMCppToolchain
from pants.backend.native.subsystems.native_compile_settings import CppCompileSettings
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import CppLibrary
from pants.backend.native.tasks.native_compile import NativeCompile
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf


class CppCompile(NativeCompile):

  options_scope = 'cpp-compile'

  # Compile only C++ library targets.
  source_target_constraint = SubclassesOf(CppLibrary)

  workunit_label = 'cpp-compile'

  @classmethod
  def implementation_version(cls):
    return super(CppCompile, cls).implementation_version() + [('CppCompile', 0)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(CppCompile, cls).subsystem_dependencies() + (
      CppCompileSettings.scoped(cls),
      NativeToolchain.scoped(cls),
    )

  @memoized_property
  def _native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def get_compile_settings(self):
    return CppCompileSettings.scoped_instance(self)

  @memoized_property
  def _cpp_toolchain(self):
    return self._request_single(LLVMCppToolchain, self._native_toolchain).cpp_toolchain

  def get_compiler(self):
    return self._cpp_toolchain.cpp_compiler
