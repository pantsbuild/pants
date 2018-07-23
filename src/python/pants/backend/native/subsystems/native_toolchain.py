# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import (Assembler, CCompiler, CppCompiler,
                                                     GCCCCompiler, GCCCLinker, GCCCppCompiler,
                                                     GCCCppLinker, GCCCppToolchain, GCCCToolchain,
                                                     Linker, LLVMCCompiler, LLVMCLinker,
                                                     LLVMCppCompiler, LLVMCppLinker,
                                                     LLVMCppToolchain, LLVMCToolchain, Platform)
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.xcode_cli_tools import XCodeCLITools
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.objects import datatype


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


@rule(LibcDev, [Select(NativeToolchain)])
def select_libc_dev(native_toolchain):
  yield native_toolchain._libc_dev


@rule(Assembler, [Select(Platform), Select(NativeToolchain)])
def select_assembler(platform, native_toolchain):
  if platform.normalized_os_name == 'darwin':
    assembler = yield Get(Assembler, XCodeCLITools, native_toolchain._xcode_cli_tools)
  else:
    assembler = yield Get(Assembler, Binutils, native_toolchain._binutils)
  yield assembler


class BaseLinker(datatype([('linker', Linker)])):
  """A Linker which is not specific to any compiler yet.

  This represents Linker objects provided by subsystems, but may need additional information to be
  usable by a specific compiler."""


# TODO: select the appropriate `Platform` in the `@rule` decl using variants!
@rule(BaseLinker, [Select(Platform), Select(NativeToolchain)])
def select_base_linker(platform, native_toolchain):
  if platform.normalized_os_name == 'darwin':
    # TODO(#5663): turn this into LLVM when lld works.
    linker = yield Get(Linker, XCodeCLITools, native_toolchain._xcode_cli_tools)
  else:
    linker = yield Get(Linker, Binutils, native_toolchain._binutils)
  base_linker = BaseLinker(linker=linker)
  yield base_linker


@rule(LLVMCToolchain, [Select(Platform), Select(NativeToolchain)])
def select_llvm_c_toolchain(platform, native_toolchain):
  original_llvm_c_compiler = yield Get(LLVMCCompiler, LLVM, native_toolchain._llvm)
  provided_clang = original_llvm_c_compiler.c_compiler

  if platform.normalized_os_name == 'darwin':
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    working_c_compiler = CCompiler(
      path_entries=(provided_clang.path_entries + xcode_clang.path_entries),
      exe_filename=provided_clang.exe_filename,
      library_dirs=(provided_clang.library_dirs + xcode_clang.library_dirs),
      include_dirs=(xcode_clang.include_dirs + provided_clang.include_dirs),
      extra_args=(['-x', 'c', '-std=c11'] + xcode_clang.extra_args))
  else:
    gcc_c_compiler = yield Get(GCCCCompiler, GCC, native_toolchain._gcc)
    provided_gcc = gcc_c_compiler.c_compiler
    working_c_compiler = CCompiler(
      path_entries=provided_clang.path_entries,
      exe_filename=provided_clang.exe_filename,
      # We need g++'s version of the GLIBCXX library to be able to run, unfortunately.
      library_dirs=(provided_gcc.library_dirs + provided_clang.library_dirs),
      include_dirs=provided_gcc.include_dirs,
      extra_args=[
        '-x', 'c', '-std=c11',
        # These mean we don't use any of the headers from our LLVM distribution.
        '-nobuiltininc',
      ])

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  libc_dev = yield Get(LibcDev, NativeToolchain, native_toolchain)
  working_linker = Linker(
    path_entries=(base_linker.path_entries + working_c_compiler.path_entries),
    exe_filename=working_c_compiler.exe_filename,
    library_dirs=(base_linker.library_dirs + working_c_compiler.library_dirs),
    linking_library_dirs=libc_dev.get_libc_dirs(platform),
    extra_args=[])

  yield LLVMCToolchain(llvm_c_compiler=LLVMCCompiler(working_c_compiler),
                       llvm_c_linker=LLVMCLinker(working_linker))


@rule(LLVMCppToolchain, [Select(Platform), Select(NativeToolchain)])
def select_llvm_cpp_toolchain(platform, native_toolchain):
  original_llvm_cpp_compiler = yield Get(LLVMCppCompiler, LLVM, native_toolchain._llvm)
  provided_clang = original_llvm_cpp_compiler.cpp_compiler

  if platform.normalized_os_name == 'darwin':
    xcode_clang = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    working_cpp_compiler = CppCompiler(
      path_entries=(provided_clang.path_entries + xcode_clang.path_entries),
      exe_filename=provided_clang.exe_filename,
      library_dirs=(provided_clang.library_dirs + xcode_clang.library_dirs),
      include_dirs=(xcode_clang.include_dirs + provided_clang.include_dirs),
      # On OSX, this uses the libc++ (LLVM) C++ standard library implementation. This is
      # feature-complete for OSX. <FIXME: insert link citation for that fact here!>
      extra_args=(['-x', 'c++', '-std=c++11'] + xcode_clang.extra_args))
    linking_library_dirs = []
    linker_extra_args = []
  else:
    gcc_cpp_compiler = yield Get(GCCCppCompiler, GCC, native_toolchain._gcc)
    provided_gpp = gcc_cpp_compiler.cpp_compiler
    working_cpp_compiler = CppCompiler(
      path_entries=provided_clang.path_entries,
      exe_filename=provided_clang.exe_filename,
      # We need g++'s version of the GLIBCXX library to be able to run, unfortunately.
      library_dirs=(provided_gpp.library_dirs + provided_clang.library_dirs),
      # NB: we use g++'s headers on Linux, and therefore their C++ standard library.
      include_dirs=provided_gpp.include_dirs,
      extra_args=[
        '-x', 'c++', '-std=c++11',
        # These mean we don't use any of the headers from our LLVM distribution.
        '-nobuiltininc',
        '-nostdinc++',
      ])
    linking_library_dirs = provided_gpp.library_dirs + provided_clang.library_dirs
    # Ensure we use libstdc++, provided by g++, during the linking stage.
    linker_extra_args=['-stdlib=libstdc++']

  libc_dev = yield Get(LibcDev, NativeToolchain, native_toolchain)
  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  working_linker = Linker(
    path_entries=(base_linker.path_entries + working_cpp_compiler.path_entries),
    exe_filename=working_cpp_compiler.exe_filename,
    library_dirs=(base_linker.library_dirs + working_cpp_compiler.library_dirs),
    linking_library_dirs=(linking_library_dirs + libc_dev.get_libc_dirs(platform)),
    extra_args=linker_extra_args)

  yield LLVMCppToolchain(llvm_cpp_compiler=LLVMCppCompiler(working_cpp_compiler),
                         llvm_cpp_linker=LLVMCppLinker(working_linker))


@rule(GCCCToolchain, [Select(Platform), Select(NativeToolchain)])
def select_gcc_c_toolchain(platform, native_toolchain):
  original_gcc_c_compiler = yield Get(GCCCCompiler, GCC, native_toolchain._gcc)
  provided_gcc = original_gcc_c_compiler.c_compiler

  # GCC needs an assembler, so we provide that (platform-specific) tool here.
  assembler = yield Get(Assembler, NativeToolchain, native_toolchain)

  if platform.normalized_os_name == 'darwin':
    # GCC needs access to some headers that are only provided by the XCode toolchain
    # currently (e.g. "_stdio.h"). These headers are unlikely to change across versions, so this is
    # probably safe.
    # TODO: we should be providing all of these (so we can eventually phase out XCodeCLITools
    # entirely).
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    new_include_dirs = xcode_clang.include_dirs + provided_gcc.include_dirs
  else:
    new_include_dirs = provided_gcc.include_dirs

  working_c_compiler = CCompiler(
    path_entries=(provided_gcc.path_entries + assembler.path_entries),
    exe_filename=provided_gcc.exe_filename,
    library_dirs=provided_gcc.library_dirs,
    include_dirs=new_include_dirs,
    extra_args=['-x', 'c', '-std=c11'])

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  libc_dev = yield Get(LibcDev, NativeToolchain, native_toolchain)
  working_linker = Linker(
    path_entries=(base_linker.path_entries + working_c_compiler.path_entries),
    exe_filename=working_c_compiler.exe_filename,
    library_dirs=(base_linker.library_dirs + working_c_compiler.library_dirs),
    linking_library_dirs=libc_dev.get_libc_dirs(platform),
    extra_args=[])

  yield GCCCToolchain(gcc_c_compiler=GCCCCompiler(working_c_compiler),
                      gcc_c_linker=GCCCLinker(working_linker))


@rule(GCCCppToolchain, [Select(Platform), Select(NativeToolchain)])
def select_gcc_cpp_toolchain(platform, native_toolchain):
  original_gcc_cpp_compiler = yield Get(GCCCppCompiler, GCC, native_toolchain._gcc)
  provided_gpp = original_gcc_cpp_compiler.cpp_compiler

  # GCC needs an assembler, so we provide that (platform-specific) tool here.
  assembler = yield Get(Assembler, NativeToolchain, native_toolchain)

  if platform.normalized_os_name == 'darwin':
    # GCC needs access to some headers that are only provided by the XCode toolchain
    # currently (e.g. "_stdio.h"). These headers are unlikely to change across versions, so this is
    # probably safe.
    # TODO: we should be providing all of these (so we can eventually phase out XCodeCLITools
    # entirely).
    xcode_clangpp = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    new_include_dirs = xcode_clangpp.include_dirs + provided_gpp.include_dirs
  else:
    new_include_dirs = provided_gpp.include_dirs

  working_cpp_compiler = CppCompiler(
    path_entries=(provided_gpp.path_entries + assembler.path_entries),
    exe_filename=provided_gpp.exe_filename,
    library_dirs=provided_gpp.library_dirs,
    include_dirs=new_include_dirs,
    extra_args=['-x', 'c++', '-std=c++11'])

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  libc_dev = yield Get(LibcDev, NativeToolchain, native_toolchain)
  working_linker = Linker(
    path_entries=(base_linker.path_entries + working_cpp_compiler.path_entries),
    exe_filename=working_cpp_compiler.exe_filename,
    library_dirs=(base_linker.library_dirs + working_cpp_compiler.library_dirs),
    linking_library_dirs=libc_dev.get_libc_dirs(platform),
    extra_args=[])

  yield GCCCppToolchain(gcc_cpp_compiler=GCCCppCompiler(working_cpp_compiler),
                        gcc_cpp_linker=GCCCppLinker(working_linker))


def create_native_toolchain_rules():
  return [
    select_libc_dev,
    select_assembler,
    select_base_linker,
    select_llvm_c_toolchain,
    select_llvm_cpp_toolchain,
    select_gcc_c_toolchain,
    select_gcc_cpp_toolchain,
    RootRule(NativeToolchain),
  ]
