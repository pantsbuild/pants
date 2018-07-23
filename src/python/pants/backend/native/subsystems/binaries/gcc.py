# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.config.environment import (CCompiler, CppCompiler, GCCCCompiler,
                                                     GCCCppCompiler, Platform)
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.memo import memoized_method


def _raise_empty_exception():
  raise Exception("???")


class GCC(NativeTool):
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  @memoized_method
  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  _PLATFORM_INTERMEDIATE_DIRNAME = {
    'darwin': _raise_empty_exception,
    'linux': lambda: 'x86_64-pc-linux-gnu',
  }

  @memoized_method
  def _common_lib_dirs(self, platform):
    return [
      os.path.join(self.select(), 'lib'),
      os.path.join(self.select(), 'lib64'),
      os.path.join(self.select(), 'lib/gcc'),
      os.path.join(self.select(), 'lib/gcc',
                   platform.resolve_platform_specific(self._PLATFORM_INTERMEDIATE_DIRNAME),
                   self.version()),
    ]

  @memoized_method
  def _common_include_dirs(self, platform):
    return [
      os.path.join(self.select(), 'include'),
      os.path.join(self.select(), 'lib/gcc',
                   platform.resolve_platform_specific(self._PLATFORM_INTERMEDIATE_DIRNAME),
                   self.version(),
                   'include'),
    ]

  def c_compiler(self, platform):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='gcc',
      library_dirs=self._common_lib_dirs(platform),
      include_dirs=self._common_include_dirs(platform),
      extra_args=[])

  @memoized_method
  def _cpp_include_dirs(self, platform):
    return [
      os.path.join(self.select(), 'include/c++', self.version()),
      os.path.join(self.select(), 'include/c++', self.version(),
                   platform.resolve_platform_specific(self._PLATFORM_INTERMEDIATE_DIRNAME)),
    ]

  def cpp_compiler(self, platform):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='g++',
      library_dirs=self._common_lib_dirs(platform),
      include_dirs=(self._common_include_dirs(platform) + self._cpp_include_dirs(platform)),
      extra_args=[])


@rule(GCCCCompiler, [Select(GCC), Select(Platform)])
def get_gcc(gcc, platform):
  yield GCCCCompiler(gcc.c_compiler(platform))


@rule(GCCCppCompiler, [Select(GCC), Select(Platform)])
def get_gplusplus(gcc, platform):
  yield GCCCppCompiler(gcc.cpp_compiler(platform))


def create_gcc_rules():
  return [
    get_gcc,
    get_gplusplus,
    RootRule(GCC),
  ]
