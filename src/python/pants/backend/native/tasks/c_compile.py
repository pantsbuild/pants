# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import CCompiler
from pants.backend.native.subsystems.native_compile_settings import CCompileSettings
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import CLibrary
from pants.backend.native.tasks.native_compile import NativeCompile
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf


class CCompile(NativeCompile):

  # Compile only C library targets.
  source_target_constraint = SubclassesOf(CLibrary)

  workunit_label = 'c-compile'

  @classmethod
  def implementation_version(cls):
    return super(CCompile, cls).implementation_version() + [('CCompile', 0)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(CCompile, cls).subsystem_dependencies() + (
      CCompileSettings.scoped(cls),
      NativeToolchain.scoped(cls),
    )

  @memoized_property
  def _toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def get_compile_settings(self):
    return CCompileSettings.scoped_instance(self)

  def get_compiler(self):
    return self._request_single(CCompiler, self._toolchain)

  # FIXME(#5951): don't have any command-line args in the task or in the subsystem -- rather,
  # subsystem options should be used to populate an `Executable` which produces its own arguments.
  def extra_compile_args(self):
    return ['-x', 'c', '-std=c11']
