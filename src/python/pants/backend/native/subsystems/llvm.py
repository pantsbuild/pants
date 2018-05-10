# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import ExecutablePathProvider, NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.util.memo import memoized_method


class LLVMReleaseUrlGenerator(BinaryToolUrlGenerator):

  _ARCHIVE_BASE_FMT = 'clang+llvm-{version}-x86_64-{system_id}'

  _DIST_URL_FMT = 'http://releases.llvm.org/{version}/{base}.tar.xz'

  # TODO: do exhaustiveness checking? would that be useful or desired?
  _SYSTEM_ID = {
    'darwin': 'apple-darwin',
    'linux': 'linux-gnu-ubuntu-16.04',
  }

  def generate_urls(self, version, host_platform):
    system_id = self._SYSTEM_ID[host_platform.os_name]
    archive_basename = self._ARCHIVE_BASE_FMT.format(version=version, system_id=system_id)
    return [self._DIST_URL_FMT.format(version=version, base=archive_basename)]


class LLVM(NativeTool, ExecutablePathProvider):
  options_scope = 'llvm'
  default_version = '6.0.0'
  archive_type = 'txz'

  def url_generator(self):
    return LLVMReleaseUrlGenerator()

  @memoized_method
  def select(self):
    unpacked_path = super(LLVM, self).select()
    children = os.listdir(unpacked_path)
    assert(len(children) == 1)
    return os.path.join(unpacked_path, children[0])

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]
