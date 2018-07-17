# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from contextlib import contextmanager

from pants.backend.native.config.environment import (GCCCCompiler, GCCCppCompiler, Linker,
                                                     LLVMCCompiler, LLVMCppCompiler, Platform)
from pants.backend.native.register import rules as native_backend_rules
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import is_executable, safe_open
from pants.util.process_handler import subprocess
from pants.util.strutil import create_path_env_var, safe_shlex_join
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.subsystem.subsystem_util import global_subsystem_instance, init_subsystems
from pants_test.test_base import TestBase


class TestNativeToolchain(TestBase, SchedulerTestBase):

  def setUp(self):
    super(TestNativeToolchain, self).setUp()

    init_subsystems([LibcDev, NativeToolchain], options={
      'libc': {
        'enable_libc_search': True,
      },
    })

    self.platform = Platform.create()
    self.toolchain = global_subsystem_instance(NativeToolchain)
    self.rules = native_backend_rules()

  def _sched(self, *args, **kwargs):
    return self.mk_scheduler(rules=self.rules, *args, **kwargs)

  def test_gcc_version(self):
    scheduler = self._sched()

    platform = Platform.create()

    gcc_subsystem = global_subsystem_instance(GCC)
    gcc_version = gcc_subsystem.version()

    gcc_c_compiler = self.execute_expecting_one_result(
      scheduler, GCCCCompiler, self.toolchain).value
    gcc = gcc_c_compiler.c_compiler
    gcc_version_out = self._invoke_capturing_output(
      [gcc.exe_filename, '--version'],
      env=gcc.get_invocation_environment_dict(platform))

    gcc_version_regex = re.compile('^gcc.*{}$'.format(re.escape(gcc_version)),
                                   flags=re.MULTILINE)
    self.assertIsNotNone(gcc_version_regex.search(gcc_version_out))

    gcc_cpp_compiler = self.execute_expecting_one_result(
      scheduler, GCCCppCompiler, self.toolchain).value
    gpp = gcc_cpp_compiler.cpp_compiler
    gpp_version_out = self._invoke_capturing_output(
      [gpp.exe_filename, '--version'],
      env=gpp.get_invocation_environment_dict(platform))

    gpp_version_regex = re.compile(r'^g\+\+.*{}$'.format(re.escape(gcc_version)),
                                   flags=re.MULTILINE)
    self.assertIsNotNone(gpp_version_regex.search(gpp_version_out))

  def test_clang_version(self):
    scheduler = self._sched()

    platform = Platform.create()

    llvm_subsystem = global_subsystem_instance(LLVM)
    llvm_version = llvm_subsystem.version()
    llvm_version_regex = re.compile('^clang version {}'.format(re.escape(llvm_version)),
                                    flags=re.MULTILINE)

    llvm_c_compiler = self.execute_expecting_one_result(
      scheduler, LLVMCCompiler, self.toolchain).value
    clang = llvm_c_compiler.c_compiler
    llvm_version_out = self._invoke_capturing_output(
      [clang.exe_filename, '--version'],
      env=clang.get_invocation_environment_dict(platform))

    self.assertIsNotNone(llvm_version_regex.search(llvm_version_out))

    llvm_cpp_compiler = self.execute_expecting_one_result(
      scheduler, LLVMCppCompiler, self.toolchain).value
    clangpp = llvm_cpp_compiler.cpp_compiler
    gpp_version_out = self._invoke_capturing_output(
      [clangpp.exe_filename, '--version'],
      env=clangpp.get_invocation_environment_dict(platform))

    self.assertIsNotNone(llvm_version_regex.search(gpp_version_out))

  @contextmanager
  def _hello_world_source_environment(self, file_name, contents, scheduler_request_specs):
    with temporary_dir() as tmpdir:
      scheduler = self._sched(work_dir=tmpdir)

      source_file_path = os.path.join(tmpdir, file_name)
      with safe_open(source_file_path, mode='wb') as fp:
        fp.write(contents)

      execution_request = scheduler.execution_request_literal(scheduler_request_specs)

      with pushd(tmpdir):
        yield tuple(self.execute_literal(scheduler, execution_request))

  def _invoke_compiler(self, compiler, args):
    cmd = [compiler.exe_filename] + args
    return self._invoke_capturing_output(
      cmd,
      compiler.get_invocation_environment_dict(self.platform))

  def _invoke_linker(self, linker, args):
    cmd = [linker.exe_filename] + args
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

  def _do_compile_link(self, compiler, linker, source_file, outfile, output,
                       extra_compile_args=None, extra_link_args=None,
                       extra_invocation_env=None):

    intermediate_obj_file_name = '{}.o'.format(outfile)
    self._invoke_compiler(
      compiler,
      ['-c', source_file, '-o', intermediate_obj_file_name] + (extra_compile_args or []))
    self.assertTrue(os.path.isfile(intermediate_obj_file_name))

    self._invoke_linker(
      linker,
      [intermediate_obj_file_name, '-o', outfile] + (extra_link_args or []))
    self.assertTrue(is_executable(outfile))
    program_out = self._invoke_capturing_output([os.path.abspath(outfile)],
                                                env=extra_invocation_env)
    self.assertEqual((output + '\n'), program_out)

  def test_hello_c_gcc(self):
    scheduler_request_specs = [
      (self.toolchain, GCCCCompiler),
      (self.toolchain, Linker),
    ]

    with self._hello_world_source_environment('hello.c', contents="""
#include "stdio.h"

int main() {
  printf("%s\\n", "I C the world!");
}
""", scheduler_request_specs=scheduler_request_specs) as products:

      gcc_wrapper, linker = products
      gcc = gcc_wrapper.c_compiler

      self._do_compile_link(gcc, linker, 'hello.c', 'hello_gcc', "I C the world!")

  def test_hello_c_clang(self):

    scheduler_request_specs = [
      (self.toolchain, LLVMCCompiler),
      (self.toolchain, Linker),
    ]

    with self._hello_world_source_environment('hello.c', contents="""
#include "stdio.h"

int main() {
  printf("%s\\n", "I C the world!");
}
""", scheduler_request_specs=scheduler_request_specs) as products:

      clang_wrapper, linker = products
      clang = clang_wrapper.c_compiler

      self._do_compile_link(clang, linker, 'hello.c', 'hello_clang', "I C the world!")

  def test_hello_cpp_gpp(self):

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

      # FIXME(#5951): we should be matching the linker to the compiler here, instead of trying to
      # use the same linker for everything. This is a temporary workaround.
      linker_with_gpp_workaround = Linker(
        path_entries=(gpp.path_entries + linker.path_entries),
        exe_filename=gpp.exe_filename,
        library_dirs=(gpp.library_dirs + linker.library_dirs + clangpp.library_dirs))

      self._do_compile_link(gpp, linker_with_gpp_workaround, 'hello.cpp', 'hello_gpp', "I C the world, ++ more!")

  def test_hello_cpp_clangpp(self):

    scheduler_request_specs = [
      # We need GCC to provide libstdc++.so.6, which clang needs to run on Linux.
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

      # FIXME(#5951): we should be matching the linker to the compiler here, instead of trying to
      # use the same linker for everything. This is a temporary workaround.
      linker_with_clangpp_workaround = Linker(
        path_entries=(clangpp.path_entries + linker.path_entries),
        exe_filename=clangpp.exe_filename,
        library_dirs=(gpp.library_dirs + linker.library_dirs + clangpp.library_dirs))

      lib_path_var = self.platform.resolve_platform_specific({
        'darwin': lambda: 'DYLD_LIBRARY_PATH',
        'linux': lambda: 'LD_LIBRARY_PATH',
      })
      runtime_libs_path = {lib_path_var: create_path_env_var(clangpp.library_dirs)}
      self._do_compile_link(
        clangpp, linker_with_clangpp_workaround, 'hello.cpp', 'hello_clangpp',
        "I C the world, ++ more!",
        # Otherwise we get some header errors on Linux because clang++ will prefer the system
        # headers if they are allowed, and we provide our own already in the LLVM subsystem (and
        # pass them in through CPATH).
        extra_compile_args=['-nostdinc++'],
        # LLVM will prefer LLVM's libc++ on OSX, and seemingly requires it even if it does not use
        # its own C++ library implementation, and uses libstdc++, which we provide in the linker's
        # LIBRARY_PATH. See https://libcxx.llvm.org/ for more info.
        extra_link_args=['-lc++'],
        # We need to provide libc++ on the runtime library path as well on Linux (OSX will have it
        # already).
        extra_invocation_env=runtime_libs_path)
