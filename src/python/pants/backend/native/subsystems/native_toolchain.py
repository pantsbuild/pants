# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.native.config.environment import (Assembler, CCompiler, CppCompiler,
                                                     GCCCCompiler, GCCCppCompiler,
                                                     HostLibcDevInstallation, Linker, LLVMCCompiler,
                                                     LLVMCppCompiler, Platform)
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.xcode_cli_tools import XCodeCLITools
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class NativeToolchain(Subsystem):
  """Abstraction over platform-specific tools to compile and link native code.

  When this subsystem is consumed, Pants will download and unpack archives (if necessary) which
  together provide an appropriate "native toolchain" for the host platform: a compiler and linker,
  usually. This subsystem exposes the toolchain through `@rule`s, which tasks then request during
  setup or execution (synchronously, for now).

  NB: Currently, on OSX, Pants will find and invoke the XCode command-line tools, or error out with
  installation instructions if the XCode tools could not be found.
  """

  options_scope = 'native-toolchain'

  @classmethod
  def subsystem_dependencies(cls):
    return super(NativeToolchain, cls).subsystem_dependencies() + (
      Binutils.scoped(cls),
      GCC.scoped(cls),
      LibcDev.scoped(cls),
      LLVM.scoped(cls),
      XCodeCLITools.scoped(cls),
    )

  @memoized_property
  def _binutils(self):
    return Binutils.scoped_instance(self)

  @memoized_property
  def _gcc(self):
    return GCC.scoped_instance(self)

  @memoized_property
  def _llvm(self):
    return LLVM.scoped_instance(self)

  @memoized_property
  def _xcode_cli_tools(self):
    return XCodeCLITools.scoped_instance(self)

  @memoized_property
  def _libc_dev(self):
    return LibcDev.scoped_instance(self)


@rule(Linker, [Select(Platform), Select(NativeToolchain)])
def select_linker(platform, native_toolchain):
  # TODO(#5933): make it possible to yield Get with a non-static
  # subject type and use `platform.resolve_platform_specific()`, something like:
  # linker = platform.resolve_platform_specific({
  #   'darwin': lambda: Get(Linker, XCodeCLITools, native_toolchain._xcode_cli_tools),
  #   'linux': lambda: Get(Linker, Binutils, native_toolchain._binutils),
  # })
  if platform.normalized_os_name == 'darwin':
    # TODO(#5663): turn this into LLVM when lld works.
    linker = yield Get(Linker, XCodeCLITools, native_toolchain._xcode_cli_tools)
  else:
    linker = yield Get(Linker, Binutils, native_toolchain._binutils)

  # NB: We need to link through a provided compiler's frontend, and we need to know where all the
  # compiler's libraries/etc are, so we set the executable name to the C++ compiler, which can find
  # its own set of C++-specific files for the linker if necessary. Using e.g. 'g++' as the linker
  # appears to produce byte-identical output when linking even C-only object files, and also
  # happens to work when C++ is used.
  c_compiler = yield Get(CCompiler, NativeToolchain, native_toolchain)
  cpp_compiler = yield Get(CppCompiler, NativeToolchain, native_toolchain)
  host_libc_dev = yield Get(HostLibcDevInstallation, NativeToolchain, native_toolchain)

  # NB: If needing to create an environment for process invocation that could use either a compiler
  # or a linker (e.g. when we compile native code from `python_dist()`s), use the environment from
  # the linker object (in addition to any further customizations), which has the paths from the C
  # and C++ compilers baked in.
  # FIXME(???): we need a way to compose executables hygienically.
  linker = Linker(
    path_entries=(
      c_compiler.path_entries +
      cpp_compiler.path_entries +
      linker.path_entries),
    exe_filename=cpp_compiler.exe_filename,
    library_dirs=(
      host_libc_dev.all_lib_dirs() +
      c_compiler.library_dirs +
      cpp_compiler.library_dirs +
      linker.library_dirs))

  yield linker


@rule(LLVMCCompiler, [Select(Platform), Select(NativeToolchain)])
def select_llvm_c_compiler(platform, native_toolchain):
  original_llvm_c_compiler = yield Get(LLVMCCompiler, LLVM, native_toolchain._llvm)
  provided_clang = original_llvm_c_compiler.c_compiler

  if platform.normalized_os_name == 'darwin':
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    clang_with_xcode_paths = CCompiler(
      path_entries=(provided_clang.path_entries + xcode_clang.path_entries),
      exe_filename=provided_clang.exe_filename,
      library_dirs=(provided_clang.library_dirs + xcode_clang.library_dirs),
      include_dirs=(xcode_clang.include_dirs + provided_clang.include_dirs))
    final_llvm_c_compiler = LLVMCCompiler(clang_with_xcode_paths)
  else:
    provided_gcc = yield Get(GCCCCompiler, GCC, native_toolchain._gcc)
    clang_with_gcc_libs = CCompiler(
      path_entries=provided_clang.path_entries,
      exe_filename=provided_clang.exe_filename,
      library_dirs=(provided_clang.library_dirs + provided_gcc.library_dirs),
      include_dirs=(provided_clang.include_dirs + provided_gcc.include_dirs))
    final_llvm_c_compiler = LLVMCCompiler(clang_with_gcc_libs)

  yield final_llvm_c_compiler


@rule(LLVMCppCompiler, [Select(Platform), Select(NativeToolchain)])
def select_llvm_cpp_compiler(platform, native_toolchain):
  original_llvm_cpp_compiler = yield Get(LLVMCppCompiler, LLVM, native_toolchain._llvm)
  provided_clangpp = original_llvm_cpp_compiler.cpp_compiler

  if platform.normalized_os_name == 'darwin':
    xcode_clang = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    clang_with_xcode_paths = CppCompiler(
      path_entries=(provided_clangpp.path_entries + xcode_clang.path_entries),
      exe_filename=provided_clangpp.exe_filename,
      library_dirs=(provided_clangpp.library_dirs + xcode_clang.library_dirs),
      include_dirs=(xcode_clang.include_dirs + provided_clangpp.include_dirs))
    final_llvm_cpp_compiler = LLVMCppCompiler(clang_with_xcode_paths)
  else:
    provided_gpp = yield Get(GCCCppCompiler, GCC, native_toolchain._gpp)
    clang_with_gpp_libs = CppCompiler(
      path_entries=provided_clangpp.path_entries,
      exe_filename=provided_clangpp.exe_filename,
      library_dirs=(provided_clangpp.library_dirs + provided_gpp.library_dirs),
      include_dirs=(provided_clangpp.include_dirs + provided_gpp.include_dirs))
    final_llvm_cpp_compiler = LLVMCppCompiler(clang_with_gpp_libs)

  yield final_llvm_cpp_compiler


@rule(GCCCCompiler, [Select(Platform), Select(NativeToolchain)])
def select_gcc_c_compiler(platform, native_toolchain):
  original_gcc_c_compiler = yield Get(GCCCCompiler, GCC, native_toolchain._gcc)
  provided_gcc = original_gcc_c_compiler.c_compiler

  if platform.normalized_os_name == 'darwin':
    xcode_tools_assembler = yield Get(Assembler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    assembler_paths = xcode_tools_assembler.path_entries
  else:
    binutils_assembler = yield Get(Assembler, Binutils, native_toolchain._binutils)
    assembler_paths = binutils_assembler.path_entries

  gcc_with_assembler = CCompiler(
    path_entries=(provided_gcc.path_entries + assembler_paths),
    exe_filename=provided_gcc.exe_filename,
    library_dirs=provided_gcc.library_dirs,
    include_dirs=provided_gcc.include_dirs)

  final_gcc_c_compiler = GCCCCompiler(gcc_with_assembler)
  yield final_gcc_c_compiler


@rule(GCCCppCompiler, [Select(Platform), Select(NativeToolchain)])
def select_gcc_cpp_compiler(platform, native_toolchain):
  original_gcc_cpp_compiler = yield Get(GCCCppCompiler, GCC, native_toolchain._gcc)
  provided_gpp = original_gcc_cpp_compiler.cpp_compiler

  if platform.normalized_os_name == 'darwin':
    xcode_tools_assembler = yield Get(Assembler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    assembler_paths = xcode_tools_assembler.path_entries
  else:
    binutils_assembler = yield Get(Assembler, Binutils, native_toolchain._binutils)
    assembler_paths = binutils_assembler.path_entries

  gcc_with_assembler = CppCompiler(
    path_entries=(provided_gpp.path_entries + assembler_paths),
    exe_filename=provided_gpp.exe_filename,
    library_dirs=provided_gpp.library_dirs,
    include_dirs=provided_gpp.include_dirs)

  final_gcc_cpp_compiler = GCCCppCompiler(gcc_with_assembler)
  yield final_gcc_cpp_compiler


@rule(CCompiler, [Select(NativeToolchain)])
def select_c_compiler(native_toolchain):
  llvm_c_compiler = yield Get(LLVMCCompiler, NativeToolchain, native_toolchain)
  yield llvm_c_compiler.c_compiler


@rule(CppCompiler, [Select(NativeToolchain)])
def select_cpp_compiler(native_toolchain):
  llvm_cpp_compiler = yield Get(LLVMCppCompiler, NativeToolchain, native_toolchain)
  yield llvm_cpp_compiler.cpp_compiler


@rule(HostLibcDevInstallation, [Select(Platform), Select(NativeToolchain)])
def select_libc_dev_install(platform, native_toolchain):
  host_libc_dev = platform.resolve_platform_specific({
    'darwin': lambda: None,
    'linux': lambda: native_toolchain._libc_dev.host_libc,
  })

  yield HostLibcDevInstallation(host_libc_dev=host_libc_dev)


def create_native_toolchain_rules():
  return [
    select_linker,
    select_llvm_c_compiler,
    select_llvm_cpp_compiler,
    select_gcc_c_compiler,
    select_gcc_cpp_compiler,
    select_c_compiler,
    select_cpp_compiler,
    select_libc_dev_install,
    RootRule(NativeToolchain),
  ]
