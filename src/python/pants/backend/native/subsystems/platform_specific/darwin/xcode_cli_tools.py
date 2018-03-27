# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import ExecutablePathProvider
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable
from pants.util.memo import memoized_method


class XCodeCLITools(Subsystem, ExecutablePathProvider):

  options_scope = 'xcode-cli-tools'

  # TODO: make this an option?
  _INSTALL_LOCATION = '/usr/bin'

  _REQUIRED_TOOLS = frozenset(['cc', 'c++', 'ld', 'lipo'])

  # TODO: give install instructions!
  class XCodeToolsUnavailable(Exception):
    """???"""

  def _check_executables_exist(self):
    for filename in self._REQUIRED_TOOLS:
      executable_path = os.path.join(self._INSTALL_LOCATION, filename)
      if not is_executable(executable_path):
        raise self.XCodeToolsUnavailable("The XCode CLI tools don't seem to exist!")

  @memoized_method
  def path_entries(self):
    self._check_executables_exist()

    return [self._INSTALL_LOCATION]
