# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.util.contextutil import environment_as, get_joined_path
from pants.util.process_handler import subprocess
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import global_subsystem_instance


# TODO(cosmicexplorer): can we have some form of this run in an OSX shard on
# Travis?
class TestNativeToolchain(BaseTest):

  def setUp(self):
    super(TestNativeToolchain, self).setUp()
    self.toolchain = global_subsystem_instance(NativeToolchain)

  def _invoke_capturing_output(self, cmd, cwd=None):
    if cwd is None:
      cwd = self.build_root

    toolchain_dirs = self.toolchain.path_entries()
    # FIXME(cosmicexplorer): if we're not sure which binaries are being called,
    # this isn't much of a test.
    prepended_toolchain_path = get_joined_path(
      toolchain_dirs, os.environ.copy(), prepend=True)
    try:
      with environment_as(PATH=prepended_toolchain_path):
        return subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
      raise Exception(
        "Command failed while invoking the native toolchain "
        "with code '{code}', cwd='{cwd}', cmd='{cmd}'. Combined stdout and stderr:\n{out}"
        .format(code=e.returncode, cwd=cwd, cmd=' '.join(cmd), out=e.output),
        e)

  def test_hello_c(self):
    self.create_file('hello.c', contents="""
#include "stdio.h"

int main() {
  printf("%s\\n", "hello, world!");
}
""")

    self._invoke_capturing_output(['clang', 'hello.c', '-o', 'hello_clang'])
    c_output = self._invoke_capturing_output(['./hello_clang'])
    self.assertEqual(c_output, 'hello, world!\n')

    self._invoke_capturing_output(['gcc', 'hello.c', '-o', 'hello_gcc'])
    c_output = self._invoke_capturing_output(['./hello_gcc'])
    self.assertEqual(c_output, 'hello, world!\n')

  def test_hello_cpp(self):
    self.create_file('hello.cpp', contents="""
#include <iostream>

int main() {
  std::cout << "hello, world!" << std::endl;
}
""")

    self._invoke_capturing_output(['clang++', 'hello.cpp', '-o', 'hello_clang++'])
    cpp_output = self._invoke_capturing_output(['./hello_clang++'])
    self.assertEqual(cpp_output, 'hello, world!\n')

    self._invoke_capturing_output(['g++', 'hello.cpp', '-o', 'hello_g++'])
    cpp_output = self._invoke_capturing_output(['./hello_g++'])
    self.assertEqual(cpp_output, 'hello, world!\n')
