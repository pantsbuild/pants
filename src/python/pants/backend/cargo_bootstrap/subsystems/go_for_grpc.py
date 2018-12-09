# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.binaries.binary_tool import NativeTool


class GoForGRPC(NativeTool):
  options_scope = 'go-for-grpcio-sys'
  name = 'go'
  default_version = '1.7.3'
  archive_type = 'tgz'

  def bin_dir(self):
    return os.path.join(self.select(), 'go/bin')
