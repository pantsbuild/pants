# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Linker, Platform
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.objects import datatype


class LLVM(NativeTool):
  options_scope = 'llvm'
  default_version = '6.0.0'
  archive_type = 'tgz'

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  _PLATFORM_SPECIFIC_LINKER_NAME = {
    'darwin': lambda: 'ld64.lld',
    'linux': lambda: 'lld',
  }

  def linker(self, platform):
    return Linker(
      path_entries=self.path_entries(),
      exe_filename=platform.resolve_platform_specific(
        self._PLATFORM_SPECIFIC_LINKER_NAME))

  def c_compiler(self):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang')

  def cpp_compiler(self):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang++')


class LLDRequest(datatype([('platform', Platform), ('llvm', LLVM)])):

  def __new__(cls, platform, llvm):
    return super(LLDRequest, cls).__new__(cls, platform, llvm)


@rule(Linker, [Select(Platform), Select(LLVM)])
def get_lld(platform, llvm):
  return llvm.linker(platform)


@rule(CCompiler, [Select(LLVM)])
def get_clang(llvm):
  return llvm.c_compiler()


@rule(CppCompiler, [Select(LLVM)])
def get_clang_plusplus(llvm):
  return llvm.cpp_compiler()


def create_llvm_rules():
  return [
    get_lld,
    get_clang,
    get_clang_plusplus,
    RootRule(LLVM),
  ]
