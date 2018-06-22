# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Linker, Platform
from pants.backend.native.register import rules as native_backend_rules
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import is_executable, safe_open
from pants.util.process_handler import subprocess
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.subsystem.subsystem_util import global_subsystem_instance
from pants_test.test_base import TestBase


class TestNativeToolchain(TestBase, SchedulerTestBase):

  def setUp(self):
    super(TestNativeToolchain, self).setUp()

    self.platform = Platform.create()
    self.toolchain = global_subsystem_instance(NativeToolchain)
    self.rules = native_backend_rules()

  def _sched(self, *args, **kwargs):
    return self.mk_scheduler(rules=self.rules, *args, **kwargs)

  def _invoke_compiler(self, compiler, args, cwd, platform):
    return self._invoke_capturing_output([compiler.exe_filename] + args,
                                         cwd,
                                         compiler.get_invocation_environment_dict(platform))

  def _invoke_linker(self, linker, args, cwd, platform):
    return self._invoke_capturing_output([linker.exe_filename] + args,
                                         cwd,
                                         linker.get_invocation_environment_dict(platform))

  def _invoke_capturing_output(self, cmd, cwd, env):
    try:
      with environment_as(**env):
        return subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
      raise Exception(
        "Command failed while invoking the native toolchain "
        "with code '{code}', cwd='{cwd}', cmd='{cmd}', env='{env}'. "
        "Combined stdout and stderr:\n{out}"
        .format(code=e.returncode, cwd=cwd, cmd=' '.join(cmd), env=env,
                out=e.output),
        e)

  def test_hello_c(self):

    with temporary_dir() as tmpdir:
      _scheduler = self._sched(work_dir=tmpdir)

      c_compiler = self.execute_expecting_one_result(_scheduler, CCompiler, self.toolchain).value
      linker = self.execute_expecting_one_result(_scheduler, Linker, self.toolchain).value

      source_file_path = os.path.join(tmpdir, 'hello.c')
      with safe_open(source_file_path, mode='wb') as fp:
        fp.write("""
#include "stdio.h"

int main() {
  printf("%s\\n", "hello, world!");
}
""")
      self._invoke_compiler(c_compiler, ['-c', 'hello.c', '-o', 'hello_gcc.o'], tmpdir, self.platform)
      self.assertTrue(os.path.isfile(os.path.join(tmpdir, 'hello_gcc.o')))
      self._invoke_linker(linker, ['hello_gcc.o', '-o', 'hello_gcc'], tmpdir, self.platform)
      self.assertTrue(is_executable(os.path.join(tmpdir, 'hello_gcc')))
      gcc_out = self._invoke_capturing_output(['./hello_gcc'], tmpdir, os.environ.copy())
      self.assertEqual('hello, world!\n', gcc_out)
      # FIXME: add clang testing!

  def test_hello_cpp(self):

    with temporary_dir() as tmpdir:
      _scheduler = self._sched(work_dir=tmpdir)

      cpp_compiler = self.execute_expecting_one_result(_scheduler, CppCompiler, self.toolchain).value
      linker = self.execute_expecting_one_result(_scheduler, Linker, self.toolchain).value

      source_file_path = os.path.join(tmpdir, 'hello.cpp')
      with safe_open(source_file_path, mode='wb') as fp:
        fp.write("""
#include <iostream>

int main() {
  std::cout << "hello, world!" << std::endl;
}
""")
      self._invoke_compiler(cpp_compiler, ['-c', 'hello.cpp', '-o', 'hello_gpp.o'], tmpdir, self.platform)
      self.assertTrue(os.path.isfile(os.path.join(tmpdir, 'hello_gpp.o')))
      self._invoke_linker(linker, ['hello_gpp.o', '-o', 'hello_gpp'], tmpdir, self.platform)
      self.assertTrue(is_executable(os.path.join(tmpdir, 'hello_gpp')))
      gpp_out = self._invoke_capturing_output(['./hello_gpp'], tmpdir, os.environ.copy())
      self.assertEqual('hello, world!\n', gpp_out)
      # FIXME: add clang++ testing!
