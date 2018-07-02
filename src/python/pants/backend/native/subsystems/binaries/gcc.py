# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import (CCompiler, CppCompiler, GCCCCompiler,
                                                     GCCCppCompiler)
from pants.backend.native.subsystems.utils.parse_search_dirs import ParseSearchDirs
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.memo import memoized_method, memoized_property
from pants.util.strutil import create_path_env_var


class GCC(NativeTool):
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  @classmethod
  def subsystem_dependencies(cls):
    return super(GCC, cls).subsystem_dependencies() + (ParseSearchDirs.scoped(cls),)

  @memoized_property
  def _parse_search_dirs(self):
    return ParseSearchDirs.scoped_instance(self)

  def _lib_search_dirs(self, compiler_exe, path_entries):
    return self._parse_search_dirs.get_compiler_library_dirs(
      compiler_exe,
      env={'PATH': create_path_env_var(path_entries)})

  @memoized_method
  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  def c_compiler(self):
    exe_filename = 'gcc'
    path_entries = self.path_entries()
    return CCompiler(
      path_entries=path_entries,
      exe_filename=exe_filename,
      library_dirs=self._lib_search_dirs(exe_filename, path_entries),
      include_dirs=[])

  def cpp_compiler(self):
    exe_filename = 'g++'
    path_entries = self.path_entries()
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename=exe_filename,
      library_dirs=self._lib_search_dirs(exe_filename, path_entries),
      include_dirs=[])


@rule(GCCCCompiler, [Select(GCC)])
def get_gcc(gcc):
  yield GCCCCompiler(gcc.c_compiler())


@rule(GCCCppCompiler, [Select(GCC)])
def get_gplusplus(gcc):
  yield GCCCppCompiler(gcc.cpp_compiler())


def create_gcc_rules():
  return [
    get_gcc,
    get_gplusplus,
    RootRule(GCC),
  ]
