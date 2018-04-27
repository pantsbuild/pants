# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Platform
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select


class GCC(NativeTool):
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  def c_compiler(self, platform):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='gcc',
      platform=platform)

  def cpp_compiler(self, platform):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='g++',
      platform=platform)


@rule(CCompiler, [Select(Platform), Select(GCC)])
def get_gcc(platform, gcc):
  yield gcc.c_compiler(platform)

@rule(CppCompiler, [Select(Platform), Select(GCC)])
def get_gplusplus(platform, gcc):
  yield gcc.cpp_compiler(platform)


def create_gcc_rules():
  return [
    get_gcc,
    get_gplusplus,
    RootRule(GCC),
  ]
