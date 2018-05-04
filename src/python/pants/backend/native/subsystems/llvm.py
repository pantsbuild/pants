# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import ExecutablePathProvider, NativeTool
from pants.util.memo import memoized_method, memoized_property
from pants.util.osutil import get_normalized_os_name


class LLVM(NativeTool, ExecutablePathProvider):
  options_scope = 'llvm'
  default_version = '6.0.0'
  archive_type = 'txz'

  _ARCHIVE_BASE_FMT = 'clang+llvm-{version}-x86_64-{system_id}'
  _DIST_URL_FMT = 'http://releases.llvm.org/{version}/{base}.tar.xz'

  _PLATFORM_FMT = {
    'darwin': 'apple-darwin',
    'linux': 'linux-gnu-ubuntu-16.04',
  }

  @memoized_property
  def _archive_basename(self):
    system_id = self._PLATFORM_FMT[get_normalized_os_name()]
    return self._ARCHIVE_BASE_FMT.format(version=self.version(), system_id=system_id)

  def urls(self):
    return [self._DIST_URL_FMT.format(version=self.version(), base=self._archive_basename)]

  @memoized_method
  def select(self):
    unpacked_path = super(LLVM, self).select()
    return os.path.join(unpacked_path, self._archive_basename)

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]
