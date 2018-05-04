# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import ExecutablePathProvider, NativeTool
from pants.util.osutil import get_normalized_os_name


class Clang(NativeTool, ExecutablePathProvider):
  options_scope = 'clang'
  default_version = '6.0.0'

  @property
  def archive_type(self):
    if get_normalized_os_name() == 'darwin':
      return 'txz'
    else:
      return 'tgz'

  _OSX_URL_FMT = 'https://releases.llvm.org/{version}/clang+llvm-{version}-x86_64-apple-darwin.tar.xz'

  def urls(self):
    if get_normalized_os_name() == 'darwin':
      return [self._OSX_URL_FMT.format(self.version())]
    else:
      return None

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]
