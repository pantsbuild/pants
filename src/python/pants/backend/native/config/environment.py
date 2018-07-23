# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from abc import abstractproperty
from builtins import object

from pants.engine.rules import RootRule, SingletonRule
from pants.util.objects import datatype
from pants.util.osutil import all_normalized_os_names, get_normalized_os_name
from pants.util.strutil import create_path_env_var, safe_shlex_join


class Platform(datatype(['normalized_os_name'])):

  class UnsupportedPlatformError(Exception):
    """Thrown if pants is running on an unrecognized platform."""

  @classmethod
  def create(cls):
    return Platform(get_normalized_os_name())

  _NORMALIZED_OS_NAMES = frozenset(all_normalized_os_names())

  def resolve_platform_specific(self, platform_specific_funs):
    arg_keys = frozenset(platform_specific_funs.keys())
    unknown_plats = self._NORMALIZED_OS_NAMES - arg_keys
    if unknown_plats:
      raise self.UnsupportedPlatformError(
        "platform_specific_funs {} must support platforms {}"
        .format(platform_specific_funs, list(unknown_plats)))
    extra_plats = arg_keys - self._NORMALIZED_OS_NAMES
    if extra_plats:
      raise self.UnsupportedPlatformError(
        "platform_specific_funs {} has unrecognized platforms {}"
        .format(platform_specific_funs, list(extra_plats)))

    fun_for_platform = platform_specific_funs[self.normalized_os_name]
    return fun_for_platform()


class Executable(object):

  @abstractproperty
  def path_entries(self):
    """A list of directory paths containing this executable, to be used in a subprocess's PATH.

    This may be multiple directories, e.g. if the main executable program invokes any subprocesses.
    """

  @abstractproperty
  def library_dirs(self):
    """Directories containing shared libraries required for a subprocess to run."""

  @abstractproperty
  def exe_filename(self):
    """The "entry point" -- which file to invoke when PATH is set to `path_entries()`."""

  @property
  def extra_args(self):
    return []

  def get_invocation_environment_dict(self, platform):
    lib_env_var = platform.resolve_platform_specific({
      'darwin': lambda: 'DYLD_LIBRARY_PATH',
      'linux': lambda: 'LD_LIBRARY_PATH',
    })
    return {
      'PATH': create_path_env_var(self.path_entries),
      lib_env_var: create_path_env_var(self.library_dirs),
    }


class Assembler(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
]), Executable):
  pass


class Linker(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'linking_library_dirs',
    'extra_args',
]), Executable):

  # FIXME(#5951): We need a way to compose executables more hygienically. This could be done
  # declaratively -- something like: { 'LIBRARY_PATH': DelimitedPathDirectoryEnvVar(...) }.  We
  # could also just use safe_shlex_join() and create_path_env_var() and keep all the state in the
  # environment -- but then we have to remember to use those each time we specialize.
  def get_invocation_environment_dict(self, platform):
    ret = super(Linker, self).get_invocation_environment_dict(platform).copy()

    # TODO: set all LDFLAGS in here or in further specializations of Linker instead of in individual
    # tasks.
    all_ldflags_for_platform = platform.resolve_platform_specific({
      'darwin': lambda: ['-mmacosx-version-min=10.11'],
      'linux': lambda: [],
    })
    ret.update({
      'LDSHARED': self.exe_filename,
      'LIBRARY_PATH': create_path_env_var(self.linking_library_dirs),
      'LDFLAGS': safe_shlex_join(all_ldflags_for_platform),
    })

    return ret


class CompilerMixin(Executable):

  @abstractproperty
  def include_dirs(self):
    """Directories to search for header files to #include during compilation."""

  # FIXME: LIBRARY_PATH and (DY)?LD_LIBRARY_PATH are used for entirely different purposes, but are
  # both sourced from the same `self.library_dirs`!
  def get_invocation_environment_dict(self, platform):
    ret = super(CompilerMixin, self).get_invocation_environment_dict(platform).copy()

    if self.include_dirs:
      ret['CPATH'] = create_path_env_var(self.include_dirs)

    all_cflags_for_platform = platform.resolve_platform_specific({
      'darwin': lambda: ['-mmacosx-version-min=10.11'],
      'linux': lambda: [],
    })
    ret['CFLAGS'] = safe_shlex_join(all_cflags_for_platform)

    return ret


class CCompiler(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'include_dirs',
    'extra_args',
]), CompilerMixin):

  def get_invocation_environment_dict(self, platform):
    ret = super(CCompiler, self).get_invocation_environment_dict(platform).copy()

    ret['CC'] = self.exe_filename

    return ret


class CppCompiler(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'include_dirs',
    'extra_args',
]), CompilerMixin):

  def get_invocation_environment_dict(self, platform):
    ret = super(CppCompiler, self).get_invocation_environment_dict(platform).copy()

    ret['CXX'] = self.exe_filename

    return ret


# TODO(#4020): These classes are performing the work of variants.
class GCCCCompiler(datatype([('c_compiler', CCompiler)])): pass


class GCCCLinker(datatype([('c_linker', Linker)])): pass


class GCCCppCompiler(datatype([('cpp_compiler', CppCompiler)])): pass


class GCCCppLinker(datatype([('cpp_linker', Linker)])): pass


class LLVMCCompiler(datatype([('c_compiler', CCompiler)])): pass


class LLVMCLinker(datatype([('c_linker', Linker)])): pass


class LLVMCppCompiler(datatype([('cpp_compiler', CppCompiler)])): pass


class LLVMCppLinker(datatype([('cpp_linker', Linker)])): pass


class CToolchain(datatype([('c_compiler', CCompiler), ('c_linker', Linker)])): pass


class CToolchainProvider(object):

  @abstractproperty
  def as_c_toolchain(self):
    """???"""


class LLVMCToolchain(datatype([
    ('llvm_c_compiler', LLVMCCompiler),
    ('llvm_c_linker', LLVMCLinker),
]), CToolchainProvider):

  @property
  def as_c_toolchain(self):
    return CToolchain(
      c_compiler=self.llvm_c_compiler.c_compiler,
      c_linker=self.llvm_c_linker.c_linker)


class GCCCToolchain(datatype([
    ('gcc_c_compiler', GCCCCompiler),
    ('gcc_c_linker', GCCCLinker),
]), CToolchainProvider):

  @property
  def as_c_toolchain(self):
    return CToolchain(
      c_compiler=self.gcc_c_compiler.c_compiler,
      c_linker=self.gcc_c_linker.c_linker)


class CppToolchain(datatype([('cpp_compiler', CppCompiler), ('cpp_linker', Linker)])): pass


class CppToolchainProvider(object):

  @abstractproperty
  def as_cpp_toolchain(self):
    """???"""


class LLVMCppToolchain(datatype([
    ('llvm_cpp_compiler', LLVMCppCompiler),
    ('llvm_cpp_linker', LLVMCppLinker),
]), CppToolchainProvider):

  @property
  def as_cpp_toolchain(self):
    return CppToolchain(
      cpp_compiler=self.llvm_cpp_compiler.cpp_compiler,
      cpp_linker=self.llvm_cpp_linker.cpp_linker)


class GCCCppToolchain(datatype([
    ('gcc_cpp_compiler', GCCCppCompiler),
    ('gcc_cpp_linker', GCCCppLinker),
]), CppToolchainProvider):

  @property
  def as_cpp_toolchain(self):
    return CppToolchain(
      cpp_compiler=self.gcc_cpp_compiler.cpp_compiler,
      cpp_linker=self.gcc_cpp_linker.cpp_linker)


# FIXME: make this an @rule, after we can automatically produce LibcDev and other subsystems in the
# v2 engine (see #5788).
class HostLibcDev(datatype(['crti_object', 'fingerprint'])):

  def get_lib_dir(self):
    return os.path.dirname(self.crti_object)


def create_native_environment_rules():
  return [
    RootRule(LLVMCToolchain),
    RootRule(GCCCToolchain),
    RootRule(LLVMCppToolchain),
    RootRule(LLVMCppToolchain),
    SingletonRule(Platform, Platform.create()),
  ]
