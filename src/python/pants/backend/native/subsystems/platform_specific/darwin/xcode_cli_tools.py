# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_tool import ExecutablePathProvider
from pants.subsystem.subsystem import Subsystem


class XCodeCLITools(Subsystem, ExecutablePathProvider):

  options_scope = 'xcode-cli-tools'

  def path_entries(self):
    raise Exception("???")
