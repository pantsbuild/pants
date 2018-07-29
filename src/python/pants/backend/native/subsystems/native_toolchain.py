# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import re

from twitter.common.collections import OrderedSet

from pants.backend.native.config.environment import (Assembler, CCompiler, CompilerMixin,
                                                     CppCompiler, CppToolchain, CToolchain,
                                                     GCCCppToolchain, GCCCToolchain, Linker,
                                                     LLVMCppToolchain, LLVMCToolchain, Platform)
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.backend.native.subsystems.xcode_cli_tools import XCodeCLITools
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_readable_dir
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf, datatype


logger = logging.getLogger(__name__)


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


class CompilerSystemDirSearchError(Exception):
  """Thrown for errors in finding system includes and lib dirs for a compiler."""


class DirCollectionRequest(datatype([('dir_paths', tuple)])): pass


class ExistingDirCollection(datatype([('dirs', tuple)])): pass


# FIXME: use snapshots for this!!!
@rule(ExistingDirCollection, [Select(DirCollectionRequest)])
def filter_existing_dirs(dir_collection_request):
  real_dirs = OrderedSet()
  for maybe_existing_dir in dir_collection_request.dir_paths:
    # Could use a `seen_dir_paths` set if we want to avoid pinging the fs for duplicate entries.
    if is_readable_dir(maybe_existing_dir):
      real_dirs.add(os.path.realpath(maybe_existing_dir))
    else:
      logger.debug("found non-existent or non-accessible directory '{}' from request {}"
                   .format(maybe_existing_dir, dir_collection_request))


  return ExistingDirCollection(dirs=tuple(real_dirs))


class CompilerSearchRequest(datatype([('compiler', SubclassesOf(CompilerMixin))])): pass


class LibDirsFromCompiler(ExistingDirCollection): pass


_search_dirs_libraries_regex = re.compile('^libraries: =(.*)$', flags=re.MULTILINE)


@rule(LibDirsFromCompiler, [Select(CompilerSearchRequest)])
def parse_known_lib_dirs(compiler_search_request):
  # FIXME: convert this to using `copy()` when #6269 is merged.
  cmplr = compiler_search_request.compiler
  print_search_dirs_exe = type(cmplr)(path_entries=cmplr.path_entries,
                                      exe_filename=cmplr.exe_filename,
                                      runtime_library_dirs=cmplr.runtime_library_dirs,
                                      include_dirs=cmplr.include_dirs,
                                      extra_args=['-print-search-dirs'])
  # print_search_dirs_exe = compiler_search_request.compiler.copy(extra_args=['-print-search-dirs'])
  exe_response = yield Get(
    ExecuteProcessResult,
    ExecuteProcessRequest,
    print_search_dirs_exe.as_execute_process_request())

  compiler_output = exe_response.stdout + exe_response.stderr
  libs_line = _search_dirs_libraries_regex.search(compiler_output)
  if not libs_line:
    raise CompilerSystemDirSearchError(
      "Could not parse libraries for compiler search request {!r}. Output:\n{}"
      .format(compiler_search_request, compiler_output))

  dir_collection_request = DirCollectionRequest(dir_paths=tuple(libs_line.group(1).split(':')))
  existing_dir_collection = yield Get(
    ExistingDirCollection,
    DirCollectionRequest,
    dir_collection_request)

  yield LibDirsFromCompiler(dirs=existing_dir_collection.dirs)


class IncludeDirsFromCompiler(ExistingDirCollection): pass


_include_dir_paths_start_line = '#include <...> search starts here:'
_include_dir_paths_end_line = 'End of search list.'


@rule(IncludeDirsFromCompiler, [Select(CompilerSearchRequest)])
def parse_known_include_dirs(compiler_search_request):
  # FIXME: convert this to using `copy()` when #6269 is merged.
  cmplr = compiler_search_request.compiler
  print_include_search_exe = type(cmplr)(path_entries=cmplr.path_entries,
                                      exe_filename=cmplr.exe_filename,
                                      runtime_library_dirs=cmplr.runtime_library_dirs,
                                      include_dirs=cmplr.include_dirs,
                                      extra_args=['-E', '-Wp,-v', '-'])
  # print_include_search_exe = compiler_search_request.compiler.copy(extra_args=['-E', '-Wp,-v', '-'])
  exe_response = yield Get(
    ExecuteProcessResult,
    ExecuteProcessRequest,
    print_include_search_exe.as_execute_process_request())

  compiler_output = exe_response.stdout + exe_response.stderr
  parsed_include_paths = None
  for output_line in compiler_output.split('\n'):
    if output_line == _include_dir_paths_start_line:
      parsed_include_paths = []
      continue
    elif output_line == _include_dir_paths_end_line:
      break

    if parsed_include_paths is not None:
      # Each line starts with a single initial space.
      parsed_include_paths.append(output_line[1:])

  dir_collection_request = DirCollectionRequest(dir_paths=tuple(parsed_include_paths))
  existing_dir_collection = yield Get(
    ExistingDirCollection,
    DirCollectionRequest,
    dir_collection_request)

  yield IncludeDirsFromCompiler(dirs=existing_dir_collection.dirs)


class CompilerSearchOutput(datatype([
    ('lib_dirs', LibDirsFromCompiler),
    ('include_dirs', IncludeDirsFromCompiler),
])): pass


@rule(CompilerSearchOutput, [Select(CompilerSearchRequest)])
def get_compiler_resources(compiler_search_request):
  lib_dirs = yield Get(LibDirsFromCompiler, CompilerSearchRequest, compiler_search_request)
  include_dirs = yield Get(IncludeDirsFromCompiler, CompilerSearchRequest, compiler_search_request)
  yield CompilerSearchOutput(lib_dirs=lib_dirs, include_dirs=include_dirs)


class CToolchainRequest(datatype([
    ('c_compiler', CCompiler),
    ('c_linker', Linker)
])): pass


@rule(CToolchain, [Select(CToolchainRequest)])
def resolve_c_toolchain(c_toolchain_request):
  c_compiler = c_toolchain_request.c_compiler
  c_linker = c_toolchain_request.c_linker
  compiler_search_output = yield Get(
    CompilerSearchOutput,
    CompilerSearchRequest,
    CompilerSearchRequest(compiler=c_compiler))

  # FIXME: convert these to using `copy()` when #6269 is merged.
  # resolved_c_toolchain = CToolchain(
  #   c_compiler=c_compiler.copy(include_dirs=compiler_search_output.include_dirs.dirs),
  #   c_linker=c_linker.copy(linking_library_dirs=compiler_search_output.lib_dirs.dirs)))
  resolved_c_toolchain = CToolchain(
    c_compiler=CCompiler(path_entries=c_compiler.path_entries,
                         exe_filename=c_compiler.exe_filename,
                         runtime_library_dirs=c_compiler.runtime_library_dirs,
                         include_dirs=compiler_search_output.include_dirs.dirs,
                         extra_args=c_compiler.extra_args),
    c_linker=Linker(
      path_entries=c_linker.path_entries,
      exe_filename=c_linker.exe_filename,
      runtime_library_dirs=c_linker.runtime_library_dirs,
      linking_library_dirs=compiler_search_output.lib_dirs.dirs,
      extra_args=c_linker.extra_args))

  yield resolved_c_toolchain


class CppToolchainRequest(datatype([
    ('cpp_compiler', CppCompiler),
    ('cpp_linker', Linker)
])): pass


@rule(CppToolchain, [Select(CppToolchainRequest)])
def resolve_cpp_toolchain(cpp_toolchain_request):
  cpp_compiler = cpp_toolchain_request.cpp_compiler
  cpp_linker = cpp_toolchain_request.cpp_linker
  compiler_search_output = yield Get(
    CompilerSearchOutput,
    CompilerSearchRequest,
    CompilerSearchRequest(compiler=cpp_compiler))

  # FIXME: convert these to using `copy()` when #6269 is merged.
  # resolved_cpp_toolchain = CppToolchain(
  #   cpp_compiler=cpp_compiler.copy(include_dirs=compiler_search_output.include_dirs.dirs),
  #   cpp_linker=cpp_linker.copy(linking_library_dirs=compiler_search_output.lib_dirs.dirs)))
  resolved_cpp_toolchain = CppToolchain(
    cpp_compiler=CppCompiler(path_entries=cpp_compiler.path_entries,
                         exe_filename=cpp_compiler.exe_filename,
                         runtime_library_dirs=cpp_compiler.runtime_library_dirs,
                         include_dirs=compiler_search_output.include_dirs.dirs,
                         extra_args=cpp_compiler.extra_args),
    cpp_linker=Linker(
      path_entries=cpp_linker.path_entries,
      exe_filename=cpp_linker.exe_filename,
      runtime_library_dirs=cpp_linker.runtime_library_dirs,
      linking_library_dirs=compiler_search_output.lib_dirs.dirs,
      extra_args=cpp_linker.extra_args))

  yield resolved_cpp_toolchain


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
    '-nostdinc',
  ]

  if platform.normalized_os_name == 'darwin':
    xcode_clang = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    working_c_compiler = provided_clang.copy(
      path_entries=(provided_clang.path_entries + xcode_clang.path_entries),
      runtime_library_dirs=(provided_clang.runtime_library_dirs + xcode_clang.runtime_library_dirs),
      include_dirs=(provided_clang.include_dirs + xcode_clang.include_dirs),
      extra_args=(llvm_c_compiler_args + xcode_clang.extra_args + ['-nobuiltininc']))
  else:
    gcc_install = yield Get(GCCInstallLocationForLLVM, GCC, native_toolchain._gcc)
    provided_gcc = yield Get(CCompiler, GCC, native_toolchain._gcc)
    working_c_compiler = provided_clang.copy(
      # We need g++'s version of the GLIBCXX library to be able to run, unfortunately.
      runtime_library_dirs=(provided_gcc.runtime_library_dirs +
                            provided_clang.runtime_library_dirs),
      include_dirs=provided_gcc.include_dirs,
      extra_args=(llvm_c_compiler_args + provided_clang.extra_args + gcc_install.as_clang_argv))

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  working_linker = base_linker.copy(
    path_entries=(base_linker.path_entries + working_c_compiler.path_entries),
    exe_filename=working_c_compiler.exe_filename,
    runtime_library_dirs=(base_linker.runtime_library_dirs +
                          working_c_compiler.runtime_library_dirs))

  c_toolchain_request = CToolchainRequest(
    c_compiler=working_c_compiler.with_tupled_collections,
    c_linker=working_linker.with_tupled_collections)
  resolved_toolchain = yield Get(CToolchain, CToolchainRequest, c_toolchain_request)
  yield LLVMCToolchain(resolved_toolchain)


@rule(LLVMCppToolchain, [Select(Platform), Select(NativeToolchain)])
def select_llvm_cpp_toolchain(platform, native_toolchain):
  provided_clangpp = yield Get(CppCompiler, LLVM, native_toolchain._llvm)

  # These arguments are shared across platforms.
  llvm_cpp_compiler_args = [
    '-x', 'c++', '-std=c++11',
    # This mean we don't use any of the headers from our LLVM distribution's C++ stdlib
    # implementation, or any from the host system. Instead, we use include dirs from the
    # XCodeCLITools or GCC.
    '-nostdinc',
    '-nostdinc++',
  ]

  if platform.normalized_os_name == 'darwin':
    xcode_clang = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
    working_cpp_compiler = provided_clangpp.copy(
      path_entries=(provided_clangpp.path_entries + xcode_clang.path_entries),
      runtime_library_dirs=(provided_clangpp.runtime_library_dirs +
                            xcode_clang.runtime_library_dirs),
      include_dirs=(provided_clangpp.include_dirs + xcode_clang.include_dirs),
      # On OSX, this uses the libc++ (LLVM) C++ standard library implementation. This is
      # feature-complete for OSX, but not for Linux (see https://libcxx.llvm.org/ for more info).
      extra_args=(llvm_cpp_compiler_args + xcode_clang.extra_args + ['-nobuiltininc']))
    linking_library_dirs = []
    linker_extra_args = []
  else:
    gcc_install = yield Get(GCCInstallLocationForLLVM, GCC, native_toolchain._gcc)
    provided_gpp = yield Get(CppCompiler, GCC, native_toolchain._gcc)
    working_cpp_compiler = provided_clangpp.copy(
      # We need g++'s version of the GLIBCXX library to be able to run, unfortunately.
      runtime_library_dirs=(provided_gpp.runtime_library_dirs + provided_clangpp.runtime_library_dirs),
      # NB: we use g++'s headers on Linux, and therefore their C++ standard library.
      include_dirs=provided_gpp.include_dirs,
      extra_args=(llvm_cpp_compiler_args + gcc_install.as_clang_argv))
    linking_library_dirs = provided_gpp.runtime_library_dirs + provided_clangpp.runtime_library_dirs
    # Ensure we use libstdc++, provided by g++, during the linking stage.
    linker_extra_args=['-stdlib=libstdc++']

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  working_linker = base_linker.copy(
    path_entries=(base_linker.path_entries + working_cpp_compiler.path_entries),
    exe_filename=working_cpp_compiler.exe_filename,
    runtime_library_dirs=(base_linker.runtime_library_dirs + working_cpp_compiler.runtime_library_dirs),
    linking_library_dirs=(base_linker.linking_library_dirs +
                          linking_library_dirs),
    extra_args=(base_linker.extra_args + linker_extra_args))

  cpp_toolchain_request = CppToolchainRequest(
    cpp_compiler=working_cpp_compiler.with_tupled_collections,
    cpp_linker=working_linker.with_tupled_collections)
  resolved_toolchain = yield Get(CppToolchain, CppToolchainRequest, cpp_toolchain_request)
  yield LLVMCppToolchain(resolved_toolchain)


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
    extra_args=['-x', 'c', '-std=c11', '-nostdinc'])

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  working_linker = base_linker.copy(
    path_entries=(working_c_compiler.path_entries + base_linker.path_entries),
    exe_filename=working_c_compiler.exe_filename,
    runtime_library_dirs=(base_linker.runtime_library_dirs +
                          working_c_compiler.runtime_library_dirs),
    linking_library_dirs=(base_linker.linking_library_dirs))

  c_toolchain_request = CToolchainRequest(
    c_compiler=working_c_compiler.with_tupled_collections,
    c_linker=working_linker.with_tupled_collections)
  resolved_toolchain = yield Get(CToolchain, CToolchainRequest, c_toolchain_request)
  yield GCCCToolchain(resolved_toolchain)


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
      '-nostdinc',
      '-nostdinc++',
    ]))

  base_linker_wrapper = yield Get(BaseLinker, NativeToolchain, native_toolchain)
  base_linker = base_linker_wrapper.linker
  working_linker = base_linker.copy(
    path_entries=(working_cpp_compiler.path_entries + base_linker.path_entries),
    exe_filename=working_cpp_compiler.exe_filename,
    runtime_library_dirs=(base_linker.runtime_library_dirs +
                          working_cpp_compiler.runtime_library_dirs))

  cpp_toolchain_request = CppToolchainRequest(
    cpp_compiler=working_cpp_compiler.with_tupled_collections,
    cpp_linker=working_linker.with_tupled_collections)
  resolved_toolchain = yield Get(CppToolchain, CppToolchainRequest, cpp_toolchain_request)
  yield GCCCppToolchain(resolved_toolchain)


def create_native_toolchain_rules():
  return [
    filter_existing_dirs,
    RootRule(DirCollectionRequest),
    parse_known_lib_dirs,
    parse_known_include_dirs,
    get_compiler_resources,
    RootRule(CompilerSearchRequest),
    resolve_c_toolchain,
    RootRule(CToolchainRequest),
    resolve_cpp_toolchain,
    RootRule(CppToolchainRequest),
    select_assembler,
    select_base_linker,
    select_gcc_install_location,
    select_llvm_c_toolchain,
    select_llvm_cpp_toolchain,
    select_gcc_c_toolchain,
    select_gcc_cpp_toolchain,
    RootRule(NativeToolchain),
  ]
