# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.native.config.environment import (Assembler, CCompiler, CppCompiler,
                                                     CppToolchain, CToolchain, Linker, Platform)
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.native_build_step import ToolchainVariant
from pants.backend.native.subsystems.xcode_cli_tools import XCodeCLITools
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
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
    return super().subsystem_dependencies() + (
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


class LinkerWrapperMixin:

  def for_compiler(self, compiler, platform):
    """Return a Linker object which is intended to be compatible with the given `compiler`."""
    return (self.linker
            # TODO(#6143): describe why the compiler needs to be first on the PATH!
            .sequence(compiler, exclude_list_fields=['extra_args', 'path_entries'])
            .prepend_field('path_entries', compiler.path_entries)
            .copy(exe_filename=compiler.exe_filename))


class GCCLinker(datatype([('linker', Linker)]), LinkerWrapperMixin): pass


class LLVMLinker(datatype([('linker', Linker)]), LinkerWrapperMixin): pass


class GCCCToolchain(datatype([('c_toolchain', CToolchain)])): pass


class GCCCppToolchain(datatype([('cpp_toolchain', CppToolchain)])): pass


class LLVMCToolchain(datatype([('c_toolchain', CToolchain)])): pass


class LLVMCppToolchain(datatype([('cpp_toolchain', CppToolchain)])): pass


@rule(LibcObjects, [Platform, NativeToolchain])
def select_libc_objects(platform, native_toolchain):
  # We use lambdas here to avoid searching for libc on osx, where it will fail.
  paths = platform.resolve_for_enum_variant({
    'darwin': lambda: [],
    'linux': lambda: native_toolchain._libc_dev.get_libc_objects(),
  })()
  yield LibcObjects(paths)


@rule(Assembler, [Platform, NativeToolchain])
def select_assembler(platform, native_toolchain):
  if platform == Platform.darwin:
    assembler = yield Get(Assembler, XCodeCLITools, native_toolchain._xcode_cli_tools)
  else:
    assembler = yield Get(Assembler, Binutils, native_toolchain._binutils)
  yield assembler


class BaseLinker(datatype([('linker', Linker)])):
  """A Linker which is not specific to any compiler yet.

  This represents Linker objects provided by subsystems, but may need additional information to be
  usable by a specific compiler."""


# TODO: select the appropriate `Platform` in the `@rule` decl using variants!
@rule(BaseLinker, [Platform, NativeToolchain])
def select_base_linker(platform, native_toolchain):
  if platform == Platform.darwin:
    # TODO(#5663): turn this into LLVM when lld works.
    linker = yield Get(Linker, XCodeCLITools, native_toolchain._xcode_cli_tools)
  else:
    linker = yield Get(Linker, Binutils, native_toolchain._binutils)
  base_linker = BaseLinker(linker=linker)
  yield base_linker


@rule(GCCLinker, [NativeToolchain])
def select_gcc_linker(native_toolchain):
  base_linker = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  linker = base_linker.linker
  libc_objects = yield Get(LibcObjects, NativeToolchain, native_toolchain)
  linker_with_libc = linker.append_field('extra_object_files', libc_objects.crti_object_paths)
  yield GCCLinker(linker_with_libc)


@rule(LLVMLinker, [BaseLinker])
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
    return [f'--gcc-toolchain={self.toolchain_dir}']


@rule(GCCInstallLocationForLLVM, [GCC])
def select_gcc_install_location(gcc):
  return GCCInstallLocationForLLVM(gcc.select())


@rule(LLVMCToolchain, [Platform, NativeToolchain])
def select_llvm_c_toolchain(platform, native_toolchain):
  provided_clang = yield Get(CCompiler, LLVM, native_toolchain._llvm)

  if platform == Platform.darwin:
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    joined_c_compiler = provided_clang.sequence(xcode_clang)
  else:
    gcc_install = yield Get(GCCInstallLocationForLLVM, GCC, native_toolchain._gcc)
    provided_gcc = yield Get(CCompiler, GCC, native_toolchain._gcc)
    joined_c_compiler = (provided_clang
                         .sequence(provided_gcc)
                         .append_field('extra_args', gcc_install.as_clang_argv)
                         # We need g++'s version of the GLIBCXX library to be able to run.
                         .prepend_field('runtime_library_dirs', provided_gcc.runtime_library_dirs))

  working_c_compiler = joined_c_compiler.prepend_field('extra_args', [
    '-x', 'c', '-std=c11',
  ])

  llvm_linker_wrapper = yield Get(LLVMLinker, NativeToolchain, native_toolchain)
  working_linker = llvm_linker_wrapper.for_compiler(working_c_compiler, platform)

  yield LLVMCToolchain(CToolchain(working_c_compiler, working_linker))


@rule(LLVMCppToolchain, [Platform, NativeToolchain])
def select_llvm_cpp_toolchain(platform, native_toolchain):
  provided_clangpp = yield Get(CppCompiler, LLVM, native_toolchain._llvm)

  # On OSX, we use the libc++ (LLVM) C++ standard library implementation. This is feature-complete
  # for OSX, but not for Linux (see https://libcxx.llvm.org/ for more info).
  if platform == Platform.darwin:
    xcode_clangpp = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    joined_cpp_compiler = provided_clangpp.sequence(xcode_clangpp)
    extra_llvm_linking_library_dirs = []
    linker_extra_args = []
  else:
    gcc_install = yield Get(GCCInstallLocationForLLVM, GCC, native_toolchain._gcc)
    provided_gpp = yield Get(CppCompiler, GCC, native_toolchain._gcc)
    joined_cpp_compiler = (provided_clangpp
                           .sequence(provided_gpp)
                           # NB: we use g++'s headers on Linux, and therefore their C++ standard
                           # library.
                           .copy(include_dirs=provided_gpp.include_dirs)
                           .append_field('extra_args', gcc_install.as_clang_argv)
                           # We need g++'s version of the GLIBCXX library to be able to run.
                           .prepend_field('runtime_library_dirs', provided_gpp.runtime_library_dirs))
    extra_llvm_linking_library_dirs = provided_gpp.runtime_library_dirs + provided_clangpp.runtime_library_dirs
    # Ensure we use libstdc++, provided by g++, during the linking stage.
    linker_extra_args=['-stdlib=libstdc++']

  working_cpp_compiler = joined_cpp_compiler.prepend_field('extra_args', [
    '-x', 'c++', '-std=c++11',
    # This flag is intended to avoid using any of the headers from our LLVM distribution's C++
    # stdlib implementation, or any from the host system, and instead, use include dirs from the
    # XCodeCLITools or GCC.
    # TODO(#6143): Determine precisely what this flag does and why it's necessary.
    '-nostdinc++',
  ])

  llvm_linker_wrapper = yield Get(LLVMLinker, NativeToolchain, native_toolchain)
  working_linker = (llvm_linker_wrapper
                    .for_compiler(working_cpp_compiler, platform)
                    .append_field('linking_library_dirs', extra_llvm_linking_library_dirs)
                    .prepend_field('extra_args', linker_extra_args))

  yield LLVMCppToolchain(CppToolchain(working_cpp_compiler, working_linker))


@rule(GCCCToolchain, [Platform, NativeToolchain])
def select_gcc_c_toolchain(platform, native_toolchain):
  provided_gcc = yield Get(CCompiler, GCC, native_toolchain._gcc)

  if platform == Platform.darwin:
    # GCC needs access to some headers that are only provided by the XCode toolchain
    # currently (e.g. "_stdio.h"). These headers are unlikely to change across versions, so this is
    # probably safe.
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    joined_c_compiler = provided_gcc.sequence(xcode_clang)
  else:
    joined_c_compiler = provided_gcc

  # GCC needs an assembler, so we provide that (platform-specific) tool here.
  assembler = yield Get(Assembler, NativeToolchain, native_toolchain)
  working_c_compiler = joined_c_compiler.sequence(assembler).prepend_field('extra_args', [
    '-x', 'c', '-std=c11',
  ])

  gcc_linker_wrapper = yield Get(GCCLinker, NativeToolchain, native_toolchain)
  working_linker = gcc_linker_wrapper.for_compiler(working_c_compiler, platform)

  yield GCCCToolchain(CToolchain(working_c_compiler, working_linker))


@rule(GCCCppToolchain, [Platform, NativeToolchain])
def select_gcc_cpp_toolchain(platform, native_toolchain):
  provided_gpp = yield Get(CppCompiler, GCC, native_toolchain._gcc)

  if platform == Platform.darwin:
    # GCC needs access to some headers that are only provided by the XCode toolchain
    # currently (e.g. "_stdio.h"). These headers are unlikely to change across versions, so this is
    # probably safe.
    # TODO: we should be providing all of these (so we can eventually phase out XCodeCLITools
    # entirely).
    xcode_clangpp = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    joined_cpp_compiler = provided_gpp.sequence(xcode_clangpp)
  else:
    joined_cpp_compiler = provided_gpp

  # GCC needs an assembler, so we provide that (platform-specific) tool here.
  assembler = yield Get(Assembler, NativeToolchain, native_toolchain)
  working_cpp_compiler = joined_cpp_compiler.sequence(assembler).prepend_field('extra_args', [
    '-x', 'c++', '-std=c++11',
    # This flag is intended to avoid using any of the headers from our LLVM distribution's C++
    # stdlib implementation, or any from the host system, and instead, use include dirs from the
    # XCodeCLITools or GCC.
    # TODO(#6143): Determine precisely what this flag does and why it's necessary.
    '-nostdinc++',
  ])

  gcc_linker_wrapper = yield Get(GCCLinker, NativeToolchain, native_toolchain)
  working_linker = gcc_linker_wrapper.for_compiler(working_cpp_compiler, platform)

  yield GCCCppToolchain(CppToolchain(working_cpp_compiler, working_linker))


class ToolchainVariantRequest(datatype([
    ('toolchain', NativeToolchain),
    ('variant', ToolchainVariant),
])): pass


@rule(CToolchain, [ToolchainVariantRequest])
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


@rule(CppToolchain, [ToolchainVariantRequest])
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
