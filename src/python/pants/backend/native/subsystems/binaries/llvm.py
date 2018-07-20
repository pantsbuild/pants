# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.config.environment import (CCompiler, CppCompiler, Linker, LLVMCCompiler,
                                                     LLVMCppCompiler, Platform)
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.dirutil import is_readable_dir
from pants.util.memo import memoized_method, memoized_property


class LLVMReleaseUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://releases.llvm.org/{version}/{base}.tar.xz'

  _ARCHIVE_BASE_FMT = 'clang+llvm-{version}-x86_64-{system_id}'

  # TODO: Give a more useful error message than KeyError if the host platform was not recognized
  # (and make it easy for other BinaryTool subclasses to do this as well).
  _SYSTEM_ID = {
    'mac': 'apple-darwin',
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
      assert(is_readable_dir(llvm_base_dir))
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
      library_dirs=[])

  # FIXME: use ParseSearchDirs for this and other include directories -- we shouldn't be trying to
  # guess the path here.
  # https://github.com/pantsbuild/pants/issues/6143
  @memoized_property
  def _common_include_dirs(self):
    return [os.path.join(self.select(), 'lib/clang', self.version(), 'include')]

  @memoized_property
  def _common_lib_dirs(self):
    return [os.path.join(self.select(), 'lib')]

  def c_compiler(self):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang',
      library_dirs=self._common_lib_dirs,
      include_dirs=self._common_include_dirs)

  @memoized_property
  def _cpp_include_dirs(self):
    return [os.path.join(self.select(), 'include/c++/v1')]

  def cpp_compiler(self):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang++',
      library_dirs=self._common_lib_dirs,
      include_dirs=(self._cpp_include_dirs + self._common_include_dirs))


# FIXME(#5663): use this over the XCode linker!
@rule(Linker, [Select(Platform), Select(LLVM)])
def get_lld(platform, llvm):
  return llvm.linker(platform)


@rule(LLVMCCompiler, [Select(LLVM)])
def get_clang(llvm):
  yield LLVMCCompiler(llvm.c_compiler())


@rule(LLVMCppCompiler, [Select(LLVM)])
def get_clang_plusplus(llvm):
  yield LLVMCppCompiler(llvm.cpp_compiler())


def create_llvm_rules():
  return [
    get_lld,
    get_clang,
    get_clang_plusplus,
    RootRule(LLVM),
  ]
