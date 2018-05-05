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

  dist_url_versions = ['6.0.0']

  _ARCHIVE_BASE_FMT = 'clang+llvm-{version}-x86_64-{system_id}'
  _DIST_URL_FMT = 'http://releases.llvm.org/{version}/{base}.tar.xz'

  _SYSTEM_ID = {
    'darwin': 'apple-darwin',
    'linux': 'linux-gnu-ubuntu-16.04',
  }

  @classmethod
  def make_dist_urls(cls, version, os_name):
    return [
      cls._DIST_URL_FMT.format(version=version, base=cls._archive_basename(version, os_name)),
    ]

  @classmethod
  def _archive_basename(cls, version, os_name):
    system_id = cls._SYSTEM_ID[os_name]
    return cls._ARCHIVE_BASE_FMT.format(version=version, system_id=system_id)

  @memoized_method
  def select(self):
    unpacked_path = super(LLVM, self).select()
    children = os.listdir(unpacked_path)
    assert(len(children) == 1)
    return os.path.join(unpacked_path, children[0])

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]
