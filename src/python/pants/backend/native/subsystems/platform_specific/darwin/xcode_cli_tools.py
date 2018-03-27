# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_tool import ExecutablePathProvider
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import is_executable
from pants.util.memo import memoized_method
from pants.util.process_handler import subprocess


_HELLO_WORLD_C = """
#include "stdio.h"

int main() {
  printf("%s\\n", "hello, world!");
}
"""


_HELLO_WORLD_CPP = """
#include <iostream>

int main() {
  std::cout << "hello, world!" << std::endl;
}
"""


class XCodeCLITools(Subsystem, ExecutablePathProvider):

  options_scope = 'xcode-cli-tools'

  # TODO: make this an option?
  _INSTALL_LOCATION = '/usr/bin'

  _REQUIRED_TOOLS = frozenset(['clang', 'clang++', 'ld', 'lipo'])

  class XCodeToolsUnavailable(Exception):
    """???"""

  @classmethod
  def _check_executables_exist(cls):
    for filename in cls._REQUIRED_TOOLS:
      executable_path = os.path.join(cls._INSTALL_LOCATION, filename)
      if not is_executable(executable_path):
        raise cls.XCodeToolsUnavailable("XCode CLI tools don't seem to exist!")

  @classmethod
  def _sanity_test(cls):

    with temporary_dir() as tmpdir:

      hello_c_path = os.path.join(tmpdir, 'hello.c')
      with open(hello_c_path, 'w') as hello_c:
        hello_c.write(_HELLO_WORLD_C)

      clang_path = os.path.join(cls._INSTALL_LOCATION, 'clang')
      subprocess.check_call([clang_path, 'hello.c', '-o', 'hello_c'],
                            cwd=tmpdir)
      c_output = subprocess.check_output(['./hello_c'],
                                         cwd=tmpdir)
      if c_output != 'hello, world!\n':
        raise cls.XCodeToolsUnavailable("C sanity test failure!")

      hello_cpp_path = os.path.join(tmpdir, 'hello.cpp')
      with open(hello_cpp_path, 'w') as hello_cpp:
        hello_cpp.write(_HELLO_WORLD_CPP)

      clang_pp_path = os.path.join(cls._INSTALL_LOCATION, 'clang++')
      subprocess.check_call([clang_pp_path, 'hello.cpp', '-o', 'hello_cpp'],
                            cwd=tmpdir)
      cpp_output = subprocess.check_output(['./hello_cpp'],
                                           cwd=tmpdir)
      if cpp_output != 'hello, world!\n':
        raise cls.XCodeToolsUnavailable("C++ sanity test failure!")

  @classmethod
  @memoized_method
  def path_entries(cls):
    try:
      cls._check_executables_exist()
      cls._sanity_test()
    except cls.XCodeToolsUnavailable as e:
      raise Exception("???", e)

    return [cls._INSTALL_LOCATION]
