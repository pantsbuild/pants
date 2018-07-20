# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import (Assembler, CCompiler, CppCompiler,
                                                     GCCCCompiler, GCCCppCompiler, Linker,
                                                     LLVMCCompiler, LLVMCppCompiler, Platform)
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
  #
  # NB: We need to link through a provided compiler's frontend, and we need to know where all the
  # compiler's libraries/etc are, so we set the executable name to the C++ compiler, which can find
  # its own set of C++-specific files for the linker if necessary. Using e.g. 'g++' as the linker
  # appears to produce byte-identical output when linking even C-only object files, and also
  # happens to work when C++ is used.
  # Currently, OSX links through the clang++ frontend, and Linux links through the g++ frontend.
  if platform.normalized_os_name == 'darwin':
    # TODO(#5663): turn this into LLVM when lld works.
    linker = yield Get(Linker, XCodeCLITools, native_toolchain._xcode_cli_tools)
    llvm_c_compiler = yield Get(LLVMCCompiler, NativeToolchain, native_toolchain)
    c_compiler = llvm_c_compiler.c_compiler
    llvm_cpp_compiler = yield Get(LLVMCppCompiler, NativeToolchain, native_toolchain)
    cpp_compiler = llvm_cpp_compiler.cpp_compiler
  else:
    linker = yield Get(Linker, Binutils, native_toolchain._binutils)
    gcc_c_compiler = yield Get(GCCCCompiler, NativeToolchain, native_toolchain)
    c_compiler = gcc_c_compiler.c_compiler
    gcc_cpp_compiler = yield Get(GCCCppCompiler, NativeToolchain, native_toolchain)
    cpp_compiler = gcc_cpp_compiler.cpp_compiler

  libc_dirs = native_toolchain._libc_dev.get_libc_dirs(platform)

  # NB: If needing to create an environment for process invocation that could use either a compiler
  # or a linker (e.g. when we compile native code from `python_dist()`s), use the environment from
  # the linker object (in addition to any further customizations), which has the paths from the C
  # and C++ compilers baked in.
  # FIXME(#5951): we need a way to compose executables more hygienically.
  linker = Linker(
    path_entries=(
      cpp_compiler.path_entries +
      c_compiler.path_entries +
      linker.path_entries),
    exe_filename=cpp_compiler.exe_filename,
    library_dirs=(
      libc_dirs +
      cpp_compiler.library_dirs +
      c_compiler.library_dirs +
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
    gcc_c_compiler = yield Get(GCCCCompiler, GCC, native_toolchain._gcc)
    provided_gcc = gcc_c_compiler.c_compiler
    clang_with_gcc_libs = CCompiler(
      path_entries=provided_clang.path_entries,
      exe_filename=provided_clang.exe_filename,
      # We need this version of GLIBCXX to be able to run, unfortunately.
      library_dirs=(provided_gcc.library_dirs + provided_clang.library_dirs),
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
      include_dirs=(provided_clangpp.include_dirs + xcode_clang.include_dirs))
    final_llvm_cpp_compiler = LLVMCppCompiler(clang_with_xcode_paths)
  else:
    gcc_cpp_compiler = yield Get(GCCCppCompiler, GCC, native_toolchain._gcc)
    provided_gpp = gcc_cpp_compiler.cpp_compiler
    clang_with_gpp_libs = CppCompiler(
      path_entries=provided_clangpp.path_entries,
      exe_filename=provided_clangpp.exe_filename,
      # We need this version of GLIBCXX to be able to run, unfortunately.
      library_dirs=(provided_gpp.library_dirs + provided_clangpp.library_dirs),
      include_dirs=(provided_clangpp.include_dirs + provided_gpp.include_dirs))
    final_llvm_cpp_compiler = LLVMCppCompiler(clang_with_gpp_libs)

  yield final_llvm_cpp_compiler


@rule(GCCCCompiler, [Select(Platform), Select(NativeToolchain)])
def select_gcc_c_compiler(platform, native_toolchain):
  original_gcc_c_compiler = yield Get(GCCCCompiler, GCC, native_toolchain._gcc)
  provided_gcc = original_gcc_c_compiler.c_compiler

  # GCC needs an assembler, so we provide that (platform-specific) tool here.
  if platform.normalized_os_name == 'darwin':
    xcode_tools_assembler = yield Get(Assembler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    assembler_paths = xcode_tools_assembler.path_entries

    # GCC needs access to some headers that are only provided by the XCode toolchain
    # currently (e.g. "_stdio.h"). These headers are unlikely to change across versions, so this is
    # probably safe.
    # TODO: we should be providing all of these (so we can eventually phase out XCodeCLITools
    # entirely).
    # This mutual recursion with select_llvm_c_compiler() works because we only pull in gcc in that
    # method if we are on Linux.
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)

    new_library_dirs = provided_gcc.library_dirs + xcode_clang.library_dirs
    new_include_dirs = xcode_clang.include_dirs + provided_gcc.include_dirs
  else:
    binutils_assembler = yield Get(Assembler, Binutils, native_toolchain._binutils)
    assembler_paths = binutils_assembler.path_entries

    new_library_dirs = provided_gcc.library_dirs
    new_include_dirs = provided_gcc.include_dirs

  gcc_with_assembler = CCompiler(
    path_entries=(provided_gcc.path_entries + assembler_paths),
    exe_filename=provided_gcc.exe_filename,
    library_dirs=new_library_dirs,
    include_dirs=new_include_dirs)

  final_gcc_c_compiler = GCCCCompiler(gcc_with_assembler)
  yield final_gcc_c_compiler


@rule(GCCCppCompiler, [Select(Platform), Select(NativeToolchain)])
def select_gcc_cpp_compiler(platform, native_toolchain):
  original_gcc_cpp_compiler = yield Get(GCCCppCompiler, GCC, native_toolchain._gcc)
  provided_gpp = original_gcc_cpp_compiler.cpp_compiler

  if platform.normalized_os_name == 'darwin':
    xcode_tools_assembler = yield Get(Assembler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    assembler_paths = xcode_tools_assembler.path_entries

    xcode_clangpp = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)

    new_library_dirs = provided_gpp.library_dirs + xcode_clangpp.library_dirs
    new_include_dirs = xcode_clangpp.include_dirs + provided_gpp.include_dirs
  else:
    binutils_assembler = yield Get(Assembler, Binutils, native_toolchain._binutils)
    assembler_paths = binutils_assembler.path_entries

    new_library_dirs = provided_gpp.library_dirs
    new_include_dirs = provided_gpp.include_dirs

  gcc_with_assembler = CppCompiler(
    path_entries=(provided_gpp.path_entries + assembler_paths),
    exe_filename=provided_gpp.exe_filename,
    library_dirs=new_library_dirs,
    include_dirs=new_include_dirs)

  final_gcc_cpp_compiler = GCCCppCompiler(gcc_with_assembler)
  yield final_gcc_cpp_compiler


@rule(CCompiler, [Select(NativeToolchain), Select(Platform)])
def select_c_compiler(native_toolchain, platform):
  if platform.normalized_os_name == 'darwin':
    llvm_c_compiler = yield Get(LLVMCCompiler, NativeToolchain, native_toolchain)
    c_compiler = llvm_c_compiler.c_compiler
  else:
    gcc_c_compiler = yield Get(GCCCCompiler, NativeToolchain, native_toolchain)
    c_compiler = gcc_c_compiler.c_compiler

  yield c_compiler


@rule(CppCompiler, [Select(NativeToolchain), Select(Platform)])
def select_cpp_compiler(native_toolchain, platform):
  if platform.normalized_os_name == 'darwin':
    llvm_cpp_compiler = yield Get(LLVMCppCompiler, NativeToolchain, native_toolchain)
    cpp_compiler = llvm_cpp_compiler.cpp_compiler
  else:
    gcc_cpp_compiler = yield Get(GCCCppCompiler, NativeToolchain, native_toolchain)
    cpp_compiler = gcc_cpp_compiler.cpp_compiler

  yield cpp_compiler


def create_native_toolchain_rules():
  return [
    select_linker,
    select_llvm_c_compiler,
    select_llvm_cpp_compiler,
    select_gcc_c_compiler,
    select_gcc_cpp_compiler,
    select_c_compiler,
    select_cpp_compiler,
    RootRule(NativeToolchain),
  ]
