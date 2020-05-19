# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess
from contextlib import contextmanager

from pants.backend.native.register import rules as native_backend_rules
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.native_toolchain import (
    GCCCppToolchain,
    GCCCToolchain,
    LLVMCppToolchain,
    LLVMCToolchain,
    NativeToolchain,
)
from pants.engine.internals.scheduler_test_base import SchedulerTestBase
from pants.engine.platform import Platform, create_platform_rules
from pants.testutil.subsystem.util import global_subsystem_instance, init_subsystems
from pants.testutil.test_base import TestBase
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import is_executable, safe_open
from pants.util.strutil import safe_shlex_join


class TestNativeToolchain(TestBase, SchedulerTestBase):
    @classmethod
    def rules(cls):
        return (*native_backend_rules(), *create_platform_rules())

    def setUp(self):
        super().setUp()

        init_subsystems([LibcDev, NativeToolchain], options={"libc": {"enable_libc_search": True}})

        self.platform = Platform.current
        self.toolchain = global_subsystem_instance(NativeToolchain)

        gcc_subsystem = global_subsystem_instance(GCC)
        self.gcc_version = gcc_subsystem.version()
        llvm_subsystem = global_subsystem_instance(LLVM)
        self.llvm_version = llvm_subsystem.version()

    def _sched(self, *args, **kwargs):
        return self.mk_scheduler(rules=self.rules(), *args, **kwargs)

    def test_gcc_version(self):
        scheduler = self._sched()
        gcc_c_toolchain = self.execute_expecting_one_result(
            scheduler, GCCCToolchain, self.toolchain
        ).value

        gcc = gcc_c_toolchain.c_toolchain.c_compiler
        gcc_version_out = self._invoke_capturing_output(
            [gcc.exe_filename, "--version"], env=gcc.invocation_environment_dict
        )

        gcc_version_regex = re.compile(rf"^gcc.*{re.escape(self.gcc_version)}$", flags=re.MULTILINE)
        self.assertIsNotNone(gcc_version_regex.search(gcc_version_out))

    def test_gpp_version(self):
        scheduler = self._sched()
        gcc_cpp_toolchain = self.execute_expecting_one_result(
            scheduler, GCCCppToolchain, self.toolchain
        ).value

        gpp = gcc_cpp_toolchain.cpp_toolchain.cpp_compiler
        gpp_version_out = self._invoke_capturing_output(
            [gpp.exe_filename, "--version"], env=gpp.invocation_environment_dict
        )

        gpp_version_regex = re.compile(
            rf"^g\+\+.*{re.escape(self.gcc_version)}$", flags=re.MULTILINE
        )
        self.assertIsNotNone(gpp_version_regex.search(gpp_version_out))

    def test_clang_version(self):
        scheduler = self._sched()
        llvm_c_toolchain = self.execute_expecting_one_result(
            scheduler, LLVMCToolchain, self.toolchain
        ).value

        clang = llvm_c_toolchain.c_toolchain.c_compiler
        clang_version_out = self._invoke_capturing_output(
            [clang.exe_filename, "--version"], env=clang.invocation_environment_dict
        )

        clang_version_regex = re.compile(
            rf"^clang version {re.escape(self.llvm_version)}", flags=re.MULTILINE
        )
        self.assertIsNotNone(clang_version_regex.search(clang_version_out))

    def test_clangpp_version(self):
        scheduler = self._sched()
        clangpp_version_regex = re.compile(
            rf"^clang version {re.escape(self.llvm_version)}", flags=re.MULTILINE
        )

        llvm_cpp_toolchain = self.execute_expecting_one_result(
            scheduler, LLVMCppToolchain, self.toolchain
        ).value
        clangpp = llvm_cpp_toolchain.cpp_toolchain.cpp_compiler
        clangpp_version_out = self._invoke_capturing_output(
            [clangpp.exe_filename, "--version"], env=clangpp.invocation_environment_dict
        )

        self.assertIsNotNone(clangpp_version_regex.search(clangpp_version_out))

    @contextmanager
    def _hello_world_source_environment(self, toolchain_type, file_name, contents):
        with temporary_dir() as tmpdir:
            scheduler = self._sched(work_dir=tmpdir)

            source_file_path = os.path.join(tmpdir, file_name)
            with safe_open(source_file_path, mode="w") as fp:
                fp.write(contents)

            toolchain = self.execute_expecting_one_result(
                scheduler, toolchain_type, self.toolchain
            ).value

            with pushd(tmpdir):
                yield toolchain

    def _invoke_compiler(self, compiler, args):
        cmd = [compiler.exe_filename] + list(compiler.extra_args) + args
        env = compiler.invocation_environment_dict
        # TODO: add an `extra_args`-like field to `Executable`s which allows for overriding env vars
        # like this, but declaratively!
        env["LC_ALL"] = "C"
        return self._invoke_capturing_output(cmd, env)

    def _invoke_linker(self, linker, args):
        cmd = [linker.exe_filename] + list(linker.extra_args) + args
        return self._invoke_capturing_output(cmd, linker.invocation_environment_dict)

    def _invoke_capturing_output(self, cmd, env=None):
        env = env or {}
        try:
            with environment_as(**env):
                return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode()
        except subprocess.CalledProcessError as e:
            raise Exception(
                "Command failed while invoking the native toolchain "
                f"with code '{e.returncode}', cwd='{os.getcwd()}', cmd='{safe_shlex_join(cmd)}', "
                f"env='{env}'. Combined stdout and stderr:\n{e.output}"
            )

    def _do_compile_link(self, compiler, linker, source_file, outfile, output):

        intermediate_obj_file_name = f"{outfile}.o"
        self._invoke_compiler(compiler, ["-c", source_file, "-o", intermediate_obj_file_name])
        self.assertTrue(os.path.isfile(intermediate_obj_file_name))

        self._invoke_linker(linker, [intermediate_obj_file_name, "-o", outfile])
        self.assertTrue(is_executable(outfile))

        program_out = self._invoke_capturing_output([os.path.abspath(outfile)])
        self.assertEqual((output + "\n"), program_out)

    def test_hello_c_gcc(self):
        with self._hello_world_source_environment(
            GCCCToolchain,
            "hello.c",
            contents="""
#include "stdio.h"

int main() {
  printf("%s\\n", "I C the world!");
}
""",
        ) as gcc_c_toolchain:

            c_toolchain = gcc_c_toolchain.c_toolchain
            compiler = c_toolchain.c_compiler
            linker = c_toolchain.c_linker

            self._do_compile_link(compiler, linker, "hello.c", "hello_gcc", "I C the world!")

    def test_hello_c_clang(self):
        with self._hello_world_source_environment(
            LLVMCToolchain,
            "hello.c",
            contents="""
#include "stdio.h"

int main() {
  printf("%s\\n", "I C the world!");
}
""",
        ) as llvm_c_toolchain:

            c_toolchain = llvm_c_toolchain.c_toolchain
            compiler = c_toolchain.c_compiler
            linker = c_toolchain.c_linker

            self._do_compile_link(compiler, linker, "hello.c", "hello_clang", "I C the world!")

    def test_hello_cpp_gpp(self):
        with self._hello_world_source_environment(
            GCCCppToolchain,
            "hello.cpp",
            contents="""
#include <iostream>

int main() {
  std::cout << "I C the world, ++ more!" << std::endl;
}
""",
        ) as gcc_cpp_toolchain:

            cpp_toolchain = gcc_cpp_toolchain.cpp_toolchain
            compiler = cpp_toolchain.cpp_compiler
            linker = cpp_toolchain.cpp_linker

            self._do_compile_link(
                compiler, linker, "hello.cpp", "hello_gpp", "I C the world, ++ more!"
            )

    def test_hello_cpp_clangpp(self):
        with self._hello_world_source_environment(
            LLVMCppToolchain,
            "hello.cpp",
            contents="""
#include <iostream>

int main() {
  std::cout << "I C the world, ++ more!" << std::endl;
}
""",
        ) as llvm_cpp_toolchain:

            cpp_toolchain = llvm_cpp_toolchain.cpp_toolchain
            compiler = cpp_toolchain.cpp_compiler
            linker = cpp_toolchain.cpp_linker

            self._do_compile_link(
                compiler, linker, "hello.cpp", "hello_clangpp", "I C the world, ++ more!"
            )
