# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Platform
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.memo import memoized_property


class GCC(NativeTool):
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  @classmethod
  def subsystem_dependencies(cls):
    return super(GCC, cls).subsystem_dependencies() + (Binutils.scoped(cls),)

  @memoized_property
  def _binutils(self):
    return Binutils.scoped_instance(self)

  def _path_entries_for_platform(self, platform):
    # GCC requires an assembler 'as' to be on the path. We need to provide this on linux, so we pull
    # it from our Binutils package.
    as_assembler_path_entries = platform.resolve_platform_specific({
      'darwin': lambda: [],
      'linux': lambda: self._binutils.path_entries(),
    })
    all_path_entries = self.path_entries() + as_assembler_path_entries
    return all_path_entries

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  def c_compiler(self, platform):
    return CCompiler(
      path_entries=self._path_entries_for_platform(platform),
      exe_filename='gcc',
      platform=platform)

  def cpp_compiler(self, platform):
    return CppCompiler(
      path_entries=self._path_entries_for_platform(platform),
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
