# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Platform
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.utils.parse_search_dirs import ParseSearchDirs
from pants.backend.native.subsystems.xcode_cli_tools import XCodeCLITools
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.memo import memoized_method, memoized_property
from pants.util.strutil import create_path_env_var


class GCC(NativeTool):
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  @classmethod
  def subsystem_dependencies(cls):
    # FIXME: Binutils and XCodeCLITools should just become Select(Assembler) in @rules
    # below, when #5788 is resolved.
    return super(GCC, cls).subsystem_dependencies() + (
      Binutils.scoped(cls),
      ParseSearchDirs.scoped(cls),
      XCodeCLITools.scoped(cls),
    )

  @memoized_property
  def _binutils(self):
    return Binutils.scoped_instance(self)

  @memoized_property
  def _xcode_cli_tools(self):
    return XCodeCLITools.scoped_instance(self)

  @memoized_property
  def _parse_search_dirs_instance(self):
    return ParseSearchDirs.scoped_instance(self)

  @memoized_method
  def _get_assembler(self, platform):
    """Get a platform-specific assembler to use for compilation.

    GCC requires an assembler 'as' to be on the path. We need to provide this
    separately, so we pull it from our Binutils or XCodeCLITools packages.

    :rtype: :class:`pants.backend.native.config.environment.Assembler`
    """
    return platform.resolve_platform_specific({
      'darwin': lambda: self._xcode_cli_tools.assembler(),
      'linux': lambda: self._binutils.assembler(),
    })

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  def c_compiler(self, platform):
    exe_filename = 'gcc'
    assembler = self._get_assembler(platform)
    own_path_entries = self.path_entries()

    lib_search_dirs = self._parse_search_dirs_instance.get_compiler_library_dirs(
      compiler_exe=exe_filename,
      env={'PATH': create_path_env_var(own_path_entries)})

    return CCompiler(
      path_entries=(own_path_entries + assembler.path_entries),
      exe_filename=exe_filename,
      library_dirs=lib_search_dirs)

  def cpp_compiler(self, platform):
    exe_filename = 'g++'
    assembler = self._get_assembler(platform)
    own_path_entries = self.path_entries()

    lib_search_dirs = self._parse_search_dirs_instance.get_compiler_library_dirs(
      compiler_exe=exe_filename,
      env={'PATH': create_path_env_var(own_path_entries)})

    return CppCompiler(
      path_entries=(own_path_entries + assembler.path_entries),
      exe_filename=exe_filename,
      library_dirs=lib_search_dirs)


@rule(CCompiler, [Select(Platform), Select(GCC)])
def get_gcc(platform, gcc):
  yield gcc.c_compiler(platform)


@rule(CppCompiler, [Select(Platform), Select(GCC)])
def get_gplusplus(platform, gcc):
  yield gcc.cpp_compiler(platform)


def create_gcc_rules():
  return [
    get_gcc,
    get_gplusplus,
    RootRule(GCC),
  ]
