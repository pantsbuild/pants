# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import (Assembler, CCompiler, CppCompiler,
                                                     CppToolchain, CToolchain, GCCCppToolchain,
                                                     GCCCToolchain, Linker, LLVMCppToolchain,
                                                     LLVMCToolchain, Platform)
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


class GCCInstallLocationForLLVM(datatype(['toolchain_dir'])):
  """This class is convertible into a list of command line arguments for clang and clang++.

  This is only used on Linux. The option --gcc-toolchain stops clang from searching for another gcc
  on the host system. The option appears to only exist on Linux clang and clang++."""

  @property
  def as_clang_argv(self):
    return ['--gcc-toolchain={}'.format(self.toolchain_dir)]


@rule(GCCInstallLocationForLLVM, [Select(GCC)])
def select_gcc_install_location(gcc):
  return GCCInstallLocationForLLVM(gcc.select())


@rule(LLVMCToolchain, [Select(Platform), Select(NativeToolchain)])
def select_llvm_c_toolchain(platform, native_toolchain):
  provided_clang = yield Get(CCompiler, LLVM, native_toolchain._llvm)

  # These arguments are shared across platforms.
  llvm_c_compiler_args = [
    '-x', 'c', '-std=c11',
    '-nobuiltininc',
  ]

  if platform.normalized_os_name == 'darwin':
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    working_c_compiler = provided_clang.copy(
      path_entries=(provided_clang.path_entries + xcode_clang.path_entries),
      library_dirs=(provided_clang.library_dirs + xcode_clang.library_dirs),
      include_dirs=(provided_clang.include_dirs + xcode_clang.include_dirs),
      extra_args=(provided_clang.extra_args + llvm_c_compiler_args + xcode_clang.extra_args))
  else:
    gcc_install = yield Get(GCCInstallLocationForLLVM, GCC, native_toolchain._gcc)
    provided_gcc = yield Get(CCompiler, GCC, native_toolchain._gcc)
    working_c_compiler = provided_clang.copy(
      # We need g++'s version of the GLIBCXX library to be able to run, unfortunately.
      library_dirs=(provided_gcc.library_dirs + provided_clang.library_dirs),
      include_dirs=provided_gcc.include_dirs,
      extra_args=(llvm_c_compiler_args + provided_clang.extra_args + gcc_install.as_clang_argv))

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  libc_dev = yield Get(LibcDev, NativeToolchain, native_toolchain)
  working_linker = base_linker.copy(
    path_entries=(base_linker.path_entries + working_c_compiler.path_entries),
    exe_filename=working_c_compiler.exe_filename,
    library_dirs=(base_linker.library_dirs + working_c_compiler.library_dirs),
    linking_library_dirs=(base_linker.linking_library_dirs + libc_dev.get_libc_dirs(platform)))

  yield LLVMCToolchain(CToolchain(working_c_compiler, working_linker))


@rule(LLVMCppToolchain, [Select(Platform), Select(NativeToolchain)])
def select_llvm_cpp_toolchain(platform, native_toolchain):
  provided_clangpp = yield Get(CppCompiler, LLVM, native_toolchain._llvm)

  # These arguments are shared across platforms.
  llvm_cpp_compiler_args = [
    '-x', 'c++', '-std=c++11',
    # This mean we don't use any of the headers from our LLVM distribution's C++ stdlib
    # implementation, or any from the host system. Instead, we use include dirs from the
    # XCodeCLITools or GCC.
    '-nobuiltininc',
    '-nostdinc++',
  ]

  if platform.normalized_os_name == 'darwin':
    xcode_clang = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    working_cpp_compiler = provided_clangpp.copy(
      path_entries=(provided_clangpp.path_entries + xcode_clang.path_entries),
      library_dirs=(provided_clangpp.library_dirs + xcode_clang.library_dirs),
      include_dirs=(provided_clangpp.include_dirs + xcode_clang.include_dirs),
      # On OSX, this uses the libc++ (LLVM) C++ standard library implementation. This is
      # feature-complete for OSX, but not for Linux (see https://libcxx.llvm.org/ for more info).
      extra_args=(llvm_cpp_compiler_args + provided_clangpp.extra_args + xcode_clang.extra_args))
    linking_library_dirs = []
    linker_extra_args = []
  else:
    gcc_install = yield Get(GCCInstallLocationForLLVM, GCC, native_toolchain._gcc)
    provided_gpp = yield Get(CppCompiler, GCC, native_toolchain._gcc)
    working_cpp_compiler = provided_clangpp.copy(
      # We need g++'s version of the GLIBCXX library to be able to run, unfortunately.
      library_dirs=(provided_gpp.library_dirs + provided_clangpp.library_dirs),
      # NB: we use g++'s headers on Linux, and therefore their C++ standard library.
      include_dirs=provided_gpp.include_dirs,
      extra_args=(llvm_cpp_compiler_args + provided_clangpp.extra_args + gcc_install.as_clang_argv))
    linking_library_dirs = provided_gpp.library_dirs + provided_clangpp.library_dirs
    # Ensure we use libstdc++, provided by g++, during the linking stage.
    linker_extra_args=['-stdlib=libstdc++']

  libc_dev = yield Get(LibcDev, NativeToolchain, native_toolchain)
  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  working_linker = base_linker.copy(
    path_entries=(base_linker.path_entries + working_cpp_compiler.path_entries),
    exe_filename=working_cpp_compiler.exe_filename,
    library_dirs=(base_linker.library_dirs + working_cpp_compiler.library_dirs),
    linking_library_dirs=(base_linker.linking_library_dirs +
                          linking_library_dirs +
                          libc_dev.get_libc_dirs(platform)),
    extra_args=(base_linker.extra_args + linker_extra_args))

  yield LLVMCppToolchain(CppToolchain(working_cpp_compiler, working_linker))


@rule(GCCCToolchain, [Select(Platform), Select(NativeToolchain)])
def select_gcc_c_toolchain(platform, native_toolchain):
  provided_gcc = yield Get(CCompiler, GCC, native_toolchain._gcc)

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

  working_c_compiler = provided_gcc.copy(
    path_entries=(provided_gcc.path_entries + assembler.path_entries),
    include_dirs=new_include_dirs,
    extra_args=['-x', 'c', '-std=c11'])

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  libc_dev = yield Get(LibcDev, NativeToolchain, native_toolchain)
  working_linker = base_linker.copy(
    path_entries=(working_c_compiler.path_entries + base_linker.path_entries),
    exe_filename=working_c_compiler.exe_filename,
    library_dirs=(base_linker.library_dirs + working_c_compiler.library_dirs),
    linking_library_dirs=(base_linker.linking_library_dirs + libc_dev.get_libc_dirs(platform)))

  yield GCCCToolchain(CToolchain(working_c_compiler, working_linker))


@rule(GCCCppToolchain, [Select(Platform), Select(NativeToolchain)])
def select_gcc_cpp_toolchain(platform, native_toolchain):
  provided_gpp = yield Get(CppCompiler, GCC, native_toolchain._gcc)

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

  working_cpp_compiler = provided_gpp.copy(
    path_entries=(provided_gpp.path_entries + assembler.path_entries),
    include_dirs=new_include_dirs,
    extra_args=([
      '-x', 'c++', '-std=c++11',
      '-nostdinc++',
    ]))

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  libc_dev = yield Get(LibcDev, NativeToolchain, native_toolchain)
  working_linker = base_linker.copy(
    path_entries=(working_cpp_compiler.path_entries + base_linker.path_entries),
    exe_filename=working_cpp_compiler.exe_filename,
    library_dirs=(base_linker.library_dirs + working_cpp_compiler.library_dirs),
    linking_library_dirs=(base_linker.linking_library_dirs + libc_dev.get_libc_dirs(platform)))

  yield GCCCppToolchain(CppToolchain(working_cpp_compiler, working_linker))


def create_native_toolchain_rules():
  return [
    select_libc_dev,
    select_assembler,
    select_base_linker,
    select_gcc_install_location,
    select_llvm_c_toolchain,
    select_llvm_cpp_toolchain,
    select_gcc_c_toolchain,
    select_gcc_cpp_toolchain,
    RootRule(NativeToolchain),
  ]
