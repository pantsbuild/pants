# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Linker, Platform
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.memo import memoized_method
from pants.util.objects import datatype


class LLVMReleaseUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://releases.llvm.org/{version}/{base}.tar.xz'

  _ARCHIVE_BASE_FMT = 'clang+llvm-{version}-x86_64-{system_id}'

  # TODO(cosmicexplorer): Give a more useful error message than KeyError if the host platform was
  # not recognized (and make it easy for other BinaryTool subclasses to do this as well).
  _SYSTEM_ID = {
    'darwin': 'apple-darwin',
    'linux': 'linux-gnu-ubuntu-16.04',
  }

  def generate_urls(self, version, host_platform):
    system_id = self._SYSTEM_ID[host_platform.os_name]
    archive_basename = self._ARCHIVE_BASE_FMT.format(version=version, system_id=system_id)
    return [self._DIST_URL_FMT.format(version=version, base=archive_basename)]


class LLVM(NativeTool):
  options_scope = 'llvm'
  default_version = '6.0.0'
  archive_type = 'txz'

  def get_external_url_generator(self):
    return LLVMReleaseUrlGenerator()

  @memoized_method
  def select(self):
    unpacked_path = super(LLVM, self).select()
    # The archive from releases.llvm.org wraps the extracted content into a directory one level
    # deeper, but the one from our S3 does not.
    children = os.listdir(unpacked_path)
    if len(children) == 1:
      llvm_base_dir = os.path.join(unpacked_path, children[0])
      assert(os.path.isdir(llvm_base_dir))
      return llvm_base_dir
    return unpacked_path

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
        self._PLATFORM_SPECIFIC_LINKER_NAME),
      platform=platform)

  def c_compiler(self, platform):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang',
      platform=platform)

  def cpp_compiler(self, platform):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang++',
      platform=platform)


@rule(Linker, [Select(Platform), Select(LLVM)])
def get_lld(platform, llvm):
  return llvm.linker(platform)


@rule(CCompiler, [Select(Platform), Select(LLVM)])
def get_clang(platform, llvm):
  return llvm.c_compiler(platform)


@rule(CppCompiler, [Select(Platform), Select(LLVM)])
def get_clang_plusplus(platform, llvm):
  return llvm.cpp_compiler(platform)


def create_llvm_rules():
  return [
    get_lld,
    get_clang,
    get_clang_plusplus,
    RootRule(LLVM),
  ]
