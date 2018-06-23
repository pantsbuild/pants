# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import Assembler, CCompiler, CppCompiler, Linker
from pants.backend.native.subsystems.utils.parse_search_dirs import ParseSearchDirs
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.option.custom_types import dir_option
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable
from pants.util.memo import memoized_method, memoized_property
from pants.util.strutil import create_path_env_var


class XCodeCLITools(Subsystem):
  """Subsystem to detect and provide the XCode command line developer tools.

  This subsystem exists to give a useful error message if the tools aren't
  installed, and because the install location may not be on the PATH when Pants
  is invoked.
  """

  options_scope = 'xcode-cli-tools'

  _REQUIRED_TOOLS = frozenset([
    'as',
    'cc',
    'c++',
    'clang',
    'clang++',
    'ld',
    'lipo',
  ])

  class XCodeToolsUnavailable(Exception):
    """Thrown if the XCode CLI tools could not be located."""
  class XCodeToolsInvalid(Exception):
    """Thrown if a method within this subsystem requests a nonexistent tool."""

  @classmethod
  def register_options(cls, register):
    super(XCodeCLITools, cls).register_options(register)

    register('--xcode-cli-install-location', type=dir_option, default='/usr/bin', advanced=True,
             help='Installation location for the XCode command-line developer tools.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(XCodeCLITools, cls).subsystem_dependencies() + (ParseSearchDirs.scoped(cls),)

  @memoized_property
  def _install_location(self):
    return self.get_options().xcode_cli_install_location

  @memoized_property
  def _parse_search_dirs_instance(self):
    return ParseSearchDirs.scoped_instance(self)

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

  @memoized_method
  def path_entries(self):
    self._check_executables_exist()
    return [self._install_location]

  @classmethod
  def _verify_tool_name(cls, name):
    # TODO: introduce some more generic way to do this that can be applied to
    # provided tools as well, and actually checks whether the file exists within
    # some set of PATH entries and is executable.
    if name in cls._REQUIRED_TOOLS:
      return name
    raise cls.XCodeToolsInvalid(
      "Internal error: {!r} is not a valid tool. Known tools are: {!r}."
      .format(name, cls._REQUIRED_TOOLS))

  @memoized_method
  def assembler(self):
    return Assembler(
      path_entries=self.path_entries(),
      exe_filename=self._verify_tool_name('as'),
      library_dirs=[])

  @memoized_method
  def linker(self):
    return Linker(
      path_entries=self.path_entries(),
      exe_filename=self._verify_tool_name('ld'),
      library_dirs=[])

  @memoized_method
  def c_compiler(self):
    exe_filename = self._verify_tool_name('clang')
    path_entries = self.path_entries()
    lib_search_dirs = self._parse_search_dirs_instance.get_compiler_library_dirs(
      compiler_exe=exe_filename,
      env={'PATH': create_path_env_var(path_entries)})
    return CCompiler(
      path_entries=path_entries,
      exe_filename=exe_filename,
      library_dirs=lib_search_dirs)

  @memoized_method
  def cpp_compiler(self):
    exe_filename = self._verify_tool_name('clang++')
    path_entries = self.path_entries()
    lib_search_dirs = self._parse_search_dirs_instance.get_compiler_library_dirs(
      compiler_exe=exe_filename,
      env={'PATH': create_path_env_var(path_entries)})
    return CppCompiler(
      path_entries=path_entries,
      exe_filename=exe_filename,
      library_dirs=lib_search_dirs)

@rule(Assembler, [Select(XCodeCLITools)])
def get_assembler(xcode_cli_tools):
  return xcode_cli_tools.assembler()


@rule(Linker, [Select(XCodeCLITools)])
def get_ld(xcode_cli_tools):
  return xcode_cli_tools.linker()


@rule(CCompiler, [Select(XCodeCLITools)])
def get_clang(xcode_cli_tools):
  return xcode_cli_tools.c_compiler()


@rule(CppCompiler, [Select(XCodeCLITools)])
def get_clang_plusplus(xcode_cli_tools):
  return xcode_cli_tools.cpp_compiler()


def create_xcode_cli_tools_rules():
  return [
    get_assembler,
    get_ld,
    get_clang,
    get_clang_plusplus,
    RootRule(XCodeCLITools),
  ]
