# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Linker, Platform
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.option.custom_types import dir_option
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable
from pants.util.memo import memoized_property


class XCodeCLITools(Subsystem):
  """Subsystem to detect and provide the XCode command line developer tools.

  This subsystem exists to give a useful error message if the tools aren't
  installed, and because the install location may not be on the PATH when Pants
  is invoked.
  """

  options_scope = 'xcode-cli-tools'

  _REQUIRED_TOOLS = frozenset(['cc', 'c++', 'clang', 'clang++', 'ld', 'lipo'])

  class XCodeToolsUnavailable(Exception):
    """Thrown if the XCode CLI tools could not be located."""

  @classmethod
  def register_options(cls, register):
    super(XCodeCLITools, cls).register_options(register)

    register('--xcode-cli-install-location', type=dir_option, default='/usr/bin', advanced=True,
             help='Installation location for the XCode command-line developer tools.')

  @memoized_property
  def _install_location(self):
    return self.get_options().xcode_cli_install_location

  def _check_executables_exist(self):
    for filename in self._REQUIRED_TOOLS:
      executable_path = os.path.join(self._install_location, filename)
      if not is_executable(executable_path):
        raise self.XCodeToolsUnavailable(
          "'{exe}' is not an executable file, but it is required to build "
          "native code on this platform. You may need to install the XCode "
          "command line developer tools from the Mac App Store. "
          "(for file '{exe}' with --xcode_cli_install_location={loc!r})"
          .format(exe=filename, loc=self._install_location))

  def path_entries(self):
    self._check_executables_exist()
    return [self._install_location]

  def linker(self, platform):
    return Linker(
      path_entries=self.path_entries(),
      # FIXME(#5951): This actually links correctly for both C and C++ sources -- there should
      # probably be some testing to ensure this is correct in CI as well.
      exe_filename='clang++',
      platform=platform)

  def c_compiler(self, platform):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang',
      platform=platform)

  def cpp_compiler(self, platform):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang++',
      platform=platform)


@rule(Linker, [Select(Platform), Select(XCodeCLITools)])
def get_ld(platform, xcode_cli_tools):
  return xcode_cli_tools.linker(platform)


@rule(CCompiler, [Select(Platform), Select(XCodeCLITools)])
def get_clang(platform, xcode_cli_tools):
  return xcode_cli_tools.c_compiler(platform)


@rule(CppCompiler, [Select(Platform), Select(XCodeCLITools)])
def get_clang_plusplus(platform, xcode_cli_tools):
  return xcode_cli_tools.cpp_compiler(platform)


def create_xcode_cli_tools_rules():
  return [
    get_ld,
    get_clang,
    get_clang_plusplus,
    RootRule(XCodeCLITools),
  ]
