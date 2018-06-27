# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import (CCompiler, CppCompiler, GCCCCompiler,
                                                     GCCCppCompiler)
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.memo import memoized_method


class GCC(NativeTool):
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  @memoized_method
  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  def c_compiler(self):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='gcc',
      library_dirs=[],
      include_dirs=[])

  def cpp_compiler(self):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='g++',
      library_dirs=[],
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
