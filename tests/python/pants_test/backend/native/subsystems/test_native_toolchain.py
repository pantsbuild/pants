# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.util.contextutil import environment_as
from pants.util.osutil import get_normalized_os_name
from pants.util.process_handler import subprocess
from pants.util.strutil import create_path_env_var
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import global_subsystem_instance


class TestNativeToolchain(BaseTest):

  def setUp(self):
    super(TestNativeToolchain, self).setUp()
    self.toolchain = global_subsystem_instance(NativeToolchain)

  def _get_test_file_path(self, path):
    return os.path.join(self.build_root, path)

  def _invoke_capturing_output(self, cmd, cwd=None):
    if cwd is None:
      cwd = self.build_root

    toolchain_dirs = self.toolchain.path_entries()
    process_invocation_env = dict(PATH=create_path_env_var(toolchain_dirs))

    # FIXME: convert this to Platform#resolve_platform_specific() when #5815 is merged.
    if get_normalized_os_name() == 'linux':
      host_libc = self.toolchain.libc.host_libc
      process_invocation_env['LIBRARY_PATH'] = os.path.dirname(host_libc.crti_object)

    try:
      with environment_as(**process_invocation_env):
        return subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
      raise Exception(
        "Command failed while invoking the native toolchain "
        "with code '{code}', cwd='{cwd}', cmd='{cmd}', env='{env}'. "
        "Combined stdout and stderr:\n{out}"
        .format(code=e.returncode, cwd=cwd, cmd=' '.join(cmd), env=process_invocation_env,
                out=e.output),
        e)

  def test_hello_c(self):
    self.create_file('hello.c', contents="""
#include "stdio.h"

int main() {
  printf("%s\\n", "hello, world!");
}
""")

    self._invoke_capturing_output(['gcc', 'hello.c', '-o', 'hello_gcc'])
    gcc_out = self._invoke_capturing_output(['./hello_gcc'])
    self.assertEqual('hello, world!\n', gcc_out)

    self._invoke_capturing_output(['clang', 'hello.c', '-o', 'hello_clang'])
    clang_compile_out = self._invoke_capturing_output(['./hello_clang'])
    self.assertEqual('hello, world!\n', clang_compile_out)

  def test_hello_cpp(self):
    self.create_file('hello.cpp', contents="""
#include <iostream>

int main() {
  std::cout << "hello, world!" << std::endl;
}
""")

    self._invoke_capturing_output(['g++', 'hello.cpp', '-o', 'hello_g++'])
    gpp_output = self._invoke_capturing_output(['./hello_g++'])
    self.assertEqual(gpp_output, 'hello, world!\n')

    self._invoke_capturing_output(['clang++', 'hello.cpp', '-o', 'hello_clang++'])
    clangpp_output = self._invoke_capturing_output(['./hello_clang++'])
    self.assertEqual(clangpp_output, 'hello, world!\n')
