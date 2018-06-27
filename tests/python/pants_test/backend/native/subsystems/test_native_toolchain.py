# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.backend.native.config.environment import (GCCCCompiler, GCCCppCompiler, Linker,
                                                     LLVMCCompiler, LLVMCppCompiler, Platform)
from pants.backend.native.register import rules as native_backend_rules
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import is_executable, safe_open
from pants.util.process_handler import subprocess
from pants.util.strutil import safe_shlex_join
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.subsystem.subsystem_util import global_subsystem_instance
from pants_test.test_base import TestBase


class TestNativeToolchain(TestBase, SchedulerTestBase):

  def setUp(self):
    super(TestNativeToolchain, self).setUp()

    self.platform = Platform.create()
    self.toolchain = global_subsystem_instance(NativeToolchain)
    self.rules = native_backend_rules()

    # TODO: ???
    self.extra_compile_link_args = self.platform.resolve_platform_specific({
      'darwin': lambda: ['-mmacosx-version-min=10.11'],
      'linux': lambda: [],
    })

  def _sched(self, *args, **kwargs):
    return self.mk_scheduler(rules=self.rules, *args, **kwargs)

  @contextmanager
  def _hello_world_source_environment(self, file_name, contents, scheduler_request_specs):
    with temporary_dir() as tmpdir:
      scheduler = self._sched(work_dir=tmpdir)

      source_file_path = os.path.join(tmpdir, file_name)
      with safe_open(source_file_path, mode='wb') as fp:
        fp.write(contents)

      products, subjects = zip(*scheduler_request_specs)
      execution_request = scheduler.execution_request_literal(scheduler_request_specs)

      with pushd(tmpdir):
        yield tuple(self.execute_literal(scheduler, execution_request))

  def _invoke_compiler(self, compiler, args):
    cmd = [compiler.exe_filename] + args + self.extra_compile_link_args
    return self._invoke_capturing_output(
      cmd,
      compiler.get_invocation_environment_dict(self.platform))

  def _invoke_linker(self, linker, args):
    cmd = [linker.exe_filename] + args + self.extra_compile_link_args
    return self._invoke_capturing_output(
      cmd,
      linker.get_invocation_environment_dict(self.platform))

  def _invoke_capturing_output(self, cmd, env=None):
    if env is None:
      env = os.environ.copy()
    try:
      with environment_as(**env):
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
      raise Exception(
        "Command failed while invoking the native toolchain "
        "with code '{code}', cwd='{cwd}', cmd='{cmd}', env='{env}'. "
        "Combined stdout and stderr:\n{out}"
        .format(code=e.returncode,
                cwd=os.getcwd(),
                # safe_shlex_join() is just for pretty-printing.
                cmd=safe_shlex_join(cmd),
                env=env,
                out=e.output),
        e)

  def _do_compile_link(self, compiler, linker, source_file, outfile, output):

    intermediate_obj_file_name = '{}.o'.format(outfile)
    self._invoke_compiler(compiler, ['-c', source_file, '-o', intermediate_obj_file_name])
    self.assertTrue(os.path.isfile(intermediate_obj_file_name))

    self._invoke_linker(linker, [intermediate_obj_file_name, '-o', outfile])
    self.assertTrue(is_executable(outfile))
    program_out = self._invoke_capturing_output([os.path.abspath(outfile)])
    self.assertEqual((output + '\n'), program_out)

  def test_hello_c(self):

    scheduler_request_specs = [
      (self.toolchain, GCCCCompiler),
      (self.toolchain, LLVMCCompiler),
      (self.toolchain, Linker),
    ]

    with self._hello_world_source_environment('hello.c', contents="""
#include "stdio.h"

int main() {
  printf("%s\\n", "I C the world!");
}
""", scheduler_request_specs=scheduler_request_specs) as products:

      gcc_wrapper, clang_wrapper, linker = products
      gcc = gcc_wrapper.c_compiler
      clang = clang_wrapper.c_compiler

      self._do_compile_link(clang, linker, 'hello.c', 'hello_clang', "I C the world!")

      self._do_compile_link(gcc, linker, 'hello.c', 'hello_gcc', "I C the world!")

  def test_hello_cpp(self):

    scheduler_request_specs = [
      (self.toolchain, GCCCppCompiler),
      (self.toolchain, LLVMCppCompiler),
      (self.toolchain, Linker),
    ]

    with self._hello_world_source_environment('hello.cpp', contents="""
#include <iostream>

int main() {
  std::cout << "I C the world, ++ more!" << std::endl;
}
""", scheduler_request_specs=scheduler_request_specs) as products:

      gpp_wrapper, clangpp_wrapper, linker = products
      gpp = gpp_wrapper.cpp_compiler
      clangpp = clangpp_wrapper.cpp_compiler

      self._do_compile_link(clangpp, linker, 'hello.cpp', 'hello_clangpp', "I C the world, ++ more!")

      gpp_with_gpp_linker = Linker(
        path_entries=(gpp.path_entries + linker.path_entries),
        exe_filename=gpp.exe_filename,
        library_dirs=(gpp.library_dirs + linker.library_dirs))

      self._do_compile_link(gpp, gpp_with_gpp_linker, 'hello.cpp', 'hello_gpp',
                            "I C the world, ++ more!")
