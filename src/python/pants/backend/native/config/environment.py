# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.engine.rules import SingletonRule
from pants.util.objects import datatype
from pants.util.osutil import all_normalized_os_names, get_normalized_os_name


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
  def exe_filename(self):
    """The "entry point" -- which file to invoke when PATH is set to `path_entries()`."""


class Linker(datatype([
    'path_entries',
    'exe_filename',
    ('platform', Platform),
]), Executable):
  pass


class CCompiler(datatype([
    'path_entries',
    'exe_filename',
    ('platform', Platform),
]), Executable):
  pass


class CppCompiler(datatype([
    'path_entries',
    'exe_filename',
    ('platform', Platform),
]), Executable):
  pass


class HostLibcDevInstallation(datatype(['lib_dir', ('platform', Platform)])):
  """???/lib_dir may be None!"""


def create_native_environment_rules():
  return [
    SingletonRule(Platform, Platform.create()),
  ]
