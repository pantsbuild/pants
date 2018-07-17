# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import CppCompiler
from pants.backend.native.subsystems.native_compile_settings import CppCompileSettings
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import CppLibrary
from pants.backend.native.tasks.native_compile import NativeCompile
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf


class CppCompile(NativeCompile):

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
  def _toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def get_compile_settings(self):
    return CppCompileSettings.scoped_instance(self)

  def get_compiler(self):
    return self._request_single(CppCompiler, self._toolchain)

  def _make_compile_argv(self, compile_request):
    # FIXME: this is a temporary fix, do not do any of this kind of introspection.
    # https://github.com/pantsbuild/pants/issues/5951
    prev_argv = super(CppCompile, self)._make_compile_argv(compile_request)

    if compile_request.compiler.exe_filename == 'clang++':
      new_argv = [prev_argv[0], '-nobuiltininc', '-nostdinc++'] + prev_argv[1:]
    else:
      new_argv = prev_argv
    return new_argv

  # FIXME(#5951): don't have any command-line args in the task or in the subsystem -- rather,
  # subsystem options should be used to populate an `Executable` which produces its own arguments.
  def extra_compile_args(self):
    return ['-x', 'c++', '-std=c++11']
