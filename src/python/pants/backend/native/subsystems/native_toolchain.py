# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import (Assembler, CCompiler, CppCompiler,
                                                     CppToolchain, CToolchain, Linker, Platform)
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.native_build_step import ToolchainVariant
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


class LibcObjects(datatype(['crti_object_paths'])): pass


class GCCLinker(datatype([('linker', Linker)])): pass


class LLVMLinker(datatype([('linker', Linker)])): pass


class GCCCToolchain(datatype([('c_toolchain', CToolchain)])): pass


class GCCCppToolchain(datatype([('cpp_toolchain', CppToolchain)])): pass


class LLVMCToolchain(datatype([('c_toolchain', CToolchain)])): pass


class LLVMCppToolchain(datatype([('cpp_toolchain', CppToolchain)])): pass


@rule(LibcObjects, [Select(Platform), Select(NativeToolchain)])
def select_libc_objects(platform, native_toolchain):
  # We use lambdas here to avoid searching for libc on osx, where it will fail.
  paths = platform.resolve_for_enum_variant({
    'darwin': lambda: [],
    'linux': lambda: native_toolchain._libc_dev.get_libc_objects(),
  })()
  yield LibcObjects(paths)


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


@rule(GCCLinker, [Select(NativeToolchain)])
def select_gcc_linker(native_toolchain):
  base_linker = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  linker = base_linker.linker
  libc_objects = yield Get(LibcObjects, NativeToolchain, native_toolchain)
  linker_with_libc = linker.copy(
    extra_object_files=(linker.extra_object_files + libc_objects.crti_object_paths))
  yield GCCLinker(linker_with_libc)


@rule(LLVMLinker, [Select(BaseLinker)])
def select_llvm_linker(base_linker):
  return LLVMLinker(base_linker.linker)


class GCCInstallLocationForLLVM(datatype(['toolchain_dir'])):
  """This class is convertible into a list of command line arguments for clang and clang++.

  This is only used on Linux. The option --gcc-toolchain stops clang from searching for another gcc
  on the host system. The option appears to only exist on Linux clang and clang++.
  """

  @property
  def as_clang_argv(self):
    # TODO(#6143): describe exactly what this argument does to the clang/clang++ invocation!
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

  llvm_linker_wrapper = yield Get(LLVMLinker, NativeToolchain, native_toolchain)
  llvm_linker = llvm_linker_wrapper.linker

  # TODO(#6855): introduce a more concise way to express these compositions of executables.
  working_linker = llvm_linker.copy(
    path_entries=(llvm_linker.path_entries + working_c_compiler.path_entries),
    exe_filename=working_c_compiler.exe_filename,
    library_dirs=(llvm_linker.library_dirs + working_c_compiler.library_dirs),
  )

  yield LLVMCToolchain(CToolchain(working_c_compiler, working_linker))


@rule(LLVMCppToolchain, [Select(Platform), Select(NativeToolchain)])
def select_llvm_cpp_toolchain(platform, native_toolchain):
  provided_clangpp = yield Get(CppCompiler, LLVM, native_toolchain._llvm)

  # These arguments are shared across platforms.
  llvm_cpp_compiler_args = [
    '-x', 'c++', '-std=c++11',
    # This flag is intended to avoid using any of the headers from our LLVM distribution's C++
    # stdlib implementation, or any from the host system, and instead, use include dirs from the
    # XCodeCLITools or GCC.
    # TODO(#6143): Determine precisely what this flag does and why it's necessary.
    '-nostdinc++',
  ]

  if platform.normalized_os_name == 'darwin':
    xcode_clangpp = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    working_cpp_compiler = provided_clangpp.copy(
      path_entries=(provided_clangpp.path_entries + xcode_clangpp.path_entries),
      library_dirs=(provided_clangpp.library_dirs + xcode_clangpp.library_dirs),
      include_dirs=(provided_clangpp.include_dirs + xcode_clangpp.include_dirs),
      # On OSX, this uses the libc++ (LLVM) C++ standard library implementation. This is
      # feature-complete for OSX, but not for Linux (see https://libcxx.llvm.org/ for more info).
      extra_args=(llvm_cpp_compiler_args + provided_clangpp.extra_args + xcode_clangpp.extra_args))
    extra_linking_library_dirs = []
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
    # TODO(#6855): why are these necessary? this is very mysterious.
    extra_linking_library_dirs = provided_gpp.library_dirs + provided_clangpp.library_dirs
    # Ensure we use libstdc++, provided by g++, during the linking stage.
    linker_extra_args=['-stdlib=libstdc++']

  llvm_linker_wrapper = yield Get(LLVMLinker, NativeToolchain, native_toolchain)
  llvm_linker = llvm_linker_wrapper.linker

  working_linker = llvm_linker.copy(
    path_entries=(llvm_linker.path_entries + working_cpp_compiler.path_entries),
    exe_filename=working_cpp_compiler.exe_filename,
    library_dirs=(llvm_linker.library_dirs + working_cpp_compiler.library_dirs),
    linking_library_dirs=(llvm_linker.linking_library_dirs +
                          extra_linking_library_dirs),
    extra_args=(llvm_linker.extra_args + linker_extra_args),
  )

  yield LLVMCppToolchain(CppToolchain(working_cpp_compiler, working_linker))


@rule(GCCCToolchain, [Select(Platform), Select(NativeToolchain)])
def select_gcc_c_toolchain(platform, native_toolchain):
  provided_gcc = yield Get(CCompiler, GCC, native_toolchain._gcc)

  # GCC needs an assembler, so we provide that (platform-specific) tool here.
  assembler = yield Get(Assembler, NativeToolchain, native_toolchain)

  gcc_c_compiler_args = [
    '-x', 'c', '-std=c11',
  ]

  if platform.normalized_os_name == 'darwin':
    # GCC needs access to some headers that are only provided by the XCode toolchain
    # currently (e.g. "_stdio.h"). These headers are unlikely to change across versions, so this is
    # probably safe.
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    new_include_dirs = provided_gcc.include_dirs + xcode_clang.include_dirs
  else:
    new_include_dirs = provided_gcc.include_dirs

  working_c_compiler = provided_gcc.copy(
    path_entries=(provided_gcc.path_entries + assembler.path_entries),
    include_dirs=new_include_dirs,
    extra_args=gcc_c_compiler_args)

  gcc_linker_wrapper = yield Get(GCCLinker, NativeToolchain, native_toolchain)
  gcc_linker = gcc_linker_wrapper.linker

  working_linker = gcc_linker.copy(
    path_entries=(working_c_compiler.path_entries + gcc_linker.path_entries),
    exe_filename=working_c_compiler.exe_filename,
    library_dirs=(gcc_linker.library_dirs + working_c_compiler.library_dirs),
  )

  yield GCCCToolchain(CToolchain(working_c_compiler, working_linker))


@rule(GCCCppToolchain, [Select(Platform), Select(NativeToolchain)])
def select_gcc_cpp_toolchain(platform, native_toolchain):
  provided_gpp = yield Get(CppCompiler, GCC, native_toolchain._gcc)

  # GCC needs an assembler, so we provide that (platform-specific) tool here.
  assembler = yield Get(Assembler, NativeToolchain, native_toolchain)

  gcc_cpp_compiler_args = [
    '-x', 'c++', '-std=c++11',
    # This flag is intended to avoid using any of the headers from our LLVM distribution's C++
    # stdlib implementation, or any from the host system, and instead, use include dirs from the
    # XCodeCLITools or GCC.
    # TODO(#6143): Determine precisely what this flag does and why it's necessary.
    '-nostdinc++',
  ]

  if platform.normalized_os_name == 'darwin':
    # GCC needs access to some headers that are only provided by the XCode toolchain
    # currently (e.g. "_stdio.h"). These headers are unlikely to change across versions, so this is
    # probably safe.
    # TODO: we should be providing all of these (so we can eventually phase out XCodeCLITools
    # entirely).
    xcode_clangpp = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    working_cpp_compiler = provided_gpp.copy(
      path_entries=(provided_gpp.path_entries + assembler.path_entries),
      include_dirs=(provided_gpp.include_dirs + xcode_clangpp.include_dirs),
      extra_args=(gcc_cpp_compiler_args + provided_gpp.extra_args + xcode_clangpp.extra_args),
    )
    extra_linking_library_dirs = []
  else:
    provided_clangpp = yield Get(CppCompiler, LLVM, native_toolchain._llvm)
    working_cpp_compiler = provided_gpp.copy(
      path_entries=(provided_gpp.path_entries + assembler.path_entries),
      extra_args=(gcc_cpp_compiler_args + provided_gpp.extra_args),
    )
    extra_linking_library_dirs = provided_gpp.library_dirs + provided_clangpp.library_dirs

  gcc_linker_wrapper = yield Get(GCCLinker, NativeToolchain, native_toolchain)
  gcc_linker = gcc_linker_wrapper.linker

  working_linker = gcc_linker.copy(
    path_entries=(working_cpp_compiler.path_entries + gcc_linker.path_entries),
    exe_filename=working_cpp_compiler.exe_filename,
    library_dirs=(gcc_linker.library_dirs + working_cpp_compiler.library_dirs),
    linking_library_dirs=(gcc_linker.linking_library_dirs + extra_linking_library_dirs),
  )

  yield GCCCppToolchain(CppToolchain(working_cpp_compiler, working_linker))


class ToolchainVariantRequest(datatype([
    ('toolchain', NativeToolchain),
    ('variant', ToolchainVariant),
])): pass


@rule(CToolchain, [Select(ToolchainVariantRequest)])
def select_c_toolchain(toolchain_variant_request):
  native_toolchain = toolchain_variant_request.toolchain
  # TODO(#5933): make an enum exhaustiveness checking method that works with `yield Get(...)`!
  use_gcc = toolchain_variant_request.variant.resolve_for_enum_variant({
    'gnu': True,
    'llvm': False,
  })
  if use_gcc:
    toolchain_resolved = yield Get(GCCCToolchain, NativeToolchain, native_toolchain)
  else:
    toolchain_resolved = yield Get(LLVMCToolchain, NativeToolchain, native_toolchain)
  yield toolchain_resolved.c_toolchain


@rule(CppToolchain, [Select(ToolchainVariantRequest)])
def select_cpp_toolchain(toolchain_variant_request):
  native_toolchain = toolchain_variant_request.toolchain
  # TODO(#5933): make an enum exhaustiveness checking method that works with `yield Get(...)`!
  use_gcc = toolchain_variant_request.variant.resolve_for_enum_variant({
    'gnu': True,
    'llvm': False,
  })
  if use_gcc:
    toolchain_resolved = yield Get(GCCCppToolchain, NativeToolchain, native_toolchain)
  else:
    toolchain_resolved = yield Get(LLVMCppToolchain, NativeToolchain, native_toolchain)
  yield toolchain_resolved.cpp_toolchain


def create_native_toolchain_rules():
  return [
    select_libc_objects,
    select_assembler,
    select_base_linker,
    select_gcc_linker,
    select_llvm_linker,
    select_gcc_install_location,
    select_llvm_c_toolchain,
    select_llvm_cpp_toolchain,
    select_gcc_c_toolchain,
    select_gcc_cpp_toolchain,
    select_c_toolchain,
    select_cpp_toolchain,
    RootRule(NativeToolchain),
    RootRule(ToolchainVariantRequest),
  ]
