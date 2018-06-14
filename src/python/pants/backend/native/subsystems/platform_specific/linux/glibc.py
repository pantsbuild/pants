# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import NativeTool


class GLibc(NativeTool):
  options_scope = 'glibc'
  default_version = '2.23'
  archive_type = 'tgz'

  def lib_dir(self):
    return os.path.join(self.select(), 'lib')
