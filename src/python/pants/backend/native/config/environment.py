# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from abc import abstractproperty

from pants.engine.rules import SingletonRule
from pants.util.meta import AbstractClass
from pants.util.objects import datatype
from pants.util.osutil import all_normalized_os_names, get_normalized_os_name
from pants.util.strutil import create_path_env_var


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


class Executable(AbstractClass):

  @abstractproperty
  def path_entries(self):
    """A list of directory paths containing this executable, to be used in a subprocess's PATH.

    This may be multiple directories, e.g. if the main executable program invokes any subprocesses.

    :rtype: list of str
    """

  @abstractproperty
  def exe_filename(self):
    """The "entry point" -- which file to invoke when PATH is set to `path_entries()`.

    :rtype: str
    """

  # TODO: rename this to 'runtime_library_dirs'!
  @abstractproperty
  def library_dirs(self):
    """Directories containing shared libraries that must be on the runtime library search path.

    Note: this is for libraries needed for the current Executable to run -- see LinkerMixin below
    for libraries that are needed at link time.

    :rtype: list of str
    """

  @property
  def extra_args(self):
    """Additional arguments used when invoking this Executable.

    These are typically placed before the invocation-specific command line arguments.

    :rtype: list of str
    """
    return []

  _platform = Platform.create()

  @property
  def as_invocation_environment_dict(self):
    """A dict to use as this Executable's execution environment.

    :rtype: dict of string -> string
    """
    lib_env_var = self._platform.resolve_platform_specific({
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


class LinkerMixin(Executable):

  @abstractproperty
  def linking_library_dirs(self):
    """Directories to search for libraries needed at link time.

    :rtype: list of str
    """

  @abstractproperty
  def extra_object_files(self):
    """A list of object files required to perform a successful link.

    This includes crti.o from libc for gcc on Linux, for example.

    :rtype: list of str
    """

  @property
  def as_invocation_environment_dict(self):
    ret = super(LinkerMixin, self).as_invocation_environment_dict.copy()

    full_library_path_dirs = self.linking_library_dirs + [
      os.path.dirname(f) for f in self.extra_object_files
    ]

    ret.update({
      'LDSHARED': self.exe_filename,
      'LIBRARY_PATH': create_path_env_var(full_library_path_dirs),
    })

    return ret


class Linker(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'linking_library_dirs',
    'extra_args',
    'extra_object_files',
]), LinkerMixin): pass


class CompilerMixin(Executable):

  @abstractproperty
  def include_dirs(self):
    """Directories to search for header files to #include during compilation.

    :rtype: list of str
    """

  @property
  def as_invocation_environment_dict(self):
    ret = super(CompilerMixin, self).as_invocation_environment_dict.copy()

    if self.include_dirs:
      ret['CPATH'] = create_path_env_var(self.include_dirs)

    return ret


class CCompiler(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'include_dirs',
    'extra_args',
]), CompilerMixin):

  @property
  def as_invocation_environment_dict(self):
    ret = super(CCompiler, self).as_invocation_environment_dict.copy()

    ret['CC'] = self.exe_filename

    return ret


class CppCompiler(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'include_dirs',
    'extra_args',
]), CompilerMixin):

  @property
  def as_invocation_environment_dict(self):
    ret = super(CppCompiler, self).as_invocation_environment_dict.copy()

    ret['CXX'] = self.exe_filename

    return ret


class CToolchain(datatype([('c_compiler', CCompiler), ('c_linker', Linker)])): pass


class CppToolchain(datatype([('cpp_compiler', CppCompiler), ('cpp_linker', Linker)])): pass


# TODO: make this an @rule, after we can automatically produce LibcDev and other subsystems in the
# v2 engine (see #5788).
class HostLibcDev(datatype(['crti_object', 'fingerprint'])): pass


def create_native_environment_rules():
  return [
    SingletonRule(Platform, Platform.create()),
  ]
