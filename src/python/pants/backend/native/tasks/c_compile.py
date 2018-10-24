# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import LLVMCToolchain
from pants.backend.native.subsystems.native_build_step_settings_base import CCompileSettings
from pants.backend.native.targets.native_library import CLibrary
from pants.backend.native.tasks.native_compile import NativeCompile
from pants.util.objects import SubclassesOf


class CCompile(NativeCompile):

  options_scope = 'c-compile'

  # Compile only C library targets.
  source_target_constraint = SubclassesOf(CLibrary)

  workunit_label = 'c-compile'

  @classmethod
  def implementation_version(cls):
    return super(CCompile, cls).implementation_version() + [('CCompile', 0)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(CCompile, cls).subsystem_dependencies() + (CCompileSettings.scoped(cls),)

  def get_compile_settings(self):
    return CCompileSettings.scoped_instance(self)

  def get_compiler(self):
    return self._request_single(LLVMCToolchain, self._native_toolchain).c_toolchain.c_compiler
