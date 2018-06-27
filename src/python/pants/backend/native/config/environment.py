# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractproperty

from pants.engine.rules import SingletonRule
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
    """???"""

  @abstractproperty
  def exe_filename(self):
    """The "entry point" -- which file to invoke when PATH is set to `path_entries()`."""

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
]), Executable):

  # FIXME(???): we need a way to compose executables hygienically -- this will work because we use
  # safe shlex methods, but we should really be composing each datatype's members, and only
  # creating an environment at the very end. This could be done declaratively -- something like:
  # { 'LIBRARY_PATH': DelimitedPathDirectoryEnvVar(...) }.
  # We could also just use safe_shlex_join() and create_path_env_var() and keep all the state in the
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
      'LIBRARY_PATH': create_path_env_var(self.library_dirs),
      'LDFLAGS': safe_shlex_join(all_ldflags_for_platform),
    })

    return ret


class CompilerMixin(Executable):

  @abstractproperty
  def include_dirs(self):
    """???"""

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
]), CompilerMixin):

  def get_invocation_environment_dict(self, platform):
    ret = super(CppCompiler, self).get_invocation_environment_dict(platform).copy()

    ret['CXX'] = self.exe_filename

    return ret


# TODO(#4020): These classes are performing the work of variants.
class GCCCCompiler(datatype([('c_compiler', CCompiler)])): pass


class LLVMCCompiler(datatype([('c_compiler', CCompiler)])): pass


class GCCCppCompiler(datatype([('cpp_compiler', CppCompiler)])): pass


class LLVMCppCompiler(datatype([('cpp_compiler', CppCompiler)])): pass


# FIXME: make this an @rule, after we can automatically produce LibcDev and other subsystems in the
# v2 engine (see #5788).
class HostLibcDev(datatype(['crti_object', 'fingerprint'])):

  def get_lib_dir(self):
    return os.path.dirname(self.crti_object)


class HostLibcDevInstallation(datatype([
    # This may be None.
    'host_libc_dev',
])):

  def all_lib_dirs(self):
    if not self.host_libc_dev:
      return []
    return [self.host_libc_dev.get_lib_dir()]


def create_native_environment_rules():
  return [
    SingletonRule(Platform, Platform.create()),
  ]
