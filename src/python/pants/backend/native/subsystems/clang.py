# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import ExecutablePathProvider, NativeTool


class Clang(NativeTool, ExecutablePathProvider):
  options_scope = 'clang'
  default_version = '6.0.0'
  archive_type = 'tgz'

  _OSX_URL_FMT = 'https://releases.llvm.org/{version}/clang+llvm-{version}-x86_64-apple-darwin.tar.xz'

  # def urls(self):


  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]
