# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import NativeTool
from pants.binaries.execution_environment_mixin import ExecutionPathEnvironment


class Binutils(NativeTool, ExecutionPathEnvironment):
  options_scope = 'binutils'
  default_version = '2.30'
  archive_type = 'tgz'

  def get_additional_paths(self):
    return [os.path.join(self.select(), 'bin')]
