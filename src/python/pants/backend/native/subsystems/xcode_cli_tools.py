# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import Assembler, CCompiler, CppCompiler, Linker
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.option.custom_types import dir_option
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable
from pants.util.memo import memoized_method, memoized_property


class XCodeCLITools(Subsystem):
  """Subsystem to detect and provide the XCode command line developer tools.

  This subsystem exists to give a useful error message if the tools aren't
  installed, and because the install location may not be on the PATH when Pants
  is invoked.
  """

  options_scope = 'xcode-cli-tools'

  REQUIRED_FILES_DEFAULT = {
    'bin': [
      'as',
      'cc',
      'c++',
      'clang',
      'clang++',
      'ld',
      'lipo',
    ],
    'include': ['_stdio.h'],
    'lib': [],
  }

  _OSX_BASE_PREFIX = '/usr'
  _XCODE_TOOLCHAIN_BASE = '/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr'

  # This comes from running clang -###.
  INCLUDE_SEARCH_DIRS_DEFAULT = [
    os.path.join(_OSX_BASE_PREFIX, 'local/include'),
    os.path.join(_XCODE_TOOLCHAIN_BASE, 'lib/clang/9.1.0/include'),
    os.path.join(_XCODE_TOOLCHAIN_BASE, 'include'),
    os.path.join(_OSX_BASE_PREFIX, 'include'),
  ]

  class XCodeToolsUnavailable(Exception):
    """Thrown if the XCode CLI tools could not be located."""

  class XCodeToolsInvalid(Exception):
    """Thrown if a method within this subsystem requests a nonexistent tool."""

  @classmethod
  def register_options(cls, register):
    super(XCodeCLITools, cls).register_options(register)

    register('--install-prefix', type=dir_option, default=cls._OSX_BASE_PREFIX, advanced=True,
             help='Location where the XCode command-line developer tools have been installed. '
                  'Under this directory should be at least {} subdirectories.'
                  .format(cls.REQUIRED_FILES_DEFAULT.keys()))

    register('--required-files', type=dict, default=cls.REQUIRED_FILES_DEFAULT, advanced=True,
             help='Files that should exist within the XCode CLI tools installation.')

    register('--include-search-dirs', type=list, default=cls.INCLUDE_SEARCH_DIRS_DEFAULT,
             advanced=True,
             help='Directories to search, in order, for files in #include directives.')

  # TODO: Obtaining options values from a subsystem should be made ergonomic as we move to complete
  # #5788.
  @memoized_property
  def _install_prefix(self):
    return self.get_options().install_prefix

  @memoized_property
  def _required_files(self):
    return self.get_options().required_files

  @memoized_property
  def _include_search_dirs(self):
    return self.get_options().include_search_dirs

  @memoized_property
  def _lib_dir(self):
    return os.path.join(self._install_prefix, 'lib')

  def _check_executables_exist(self):
    for subdir, items in self._required_files.items():
      for fname in items:
        file_path = os.path.join(self._install_prefix, subdir, fname)
        if subdir == 'bin':
          if not is_executable(file_path):
            raise self.XCodeToolsUnavailable(
              "'{exe}' is not an executable file, but it is required to build "
              "native code on this platform. You may need to install the XCode "
              "command line developer tools from the Mac App Store. "
              "(with --required-files={req}, --install-prefix={pfx})"
              .format(exe=file_path, req=self._required_files, pfx=self._install_prefix))
        else:
          if not os.path.isfile(file_path):
            raise self.XCodeToolsUnavailable(
              "The file at path '{path}' does not exist, but it is required to build "
              "native code on this platform. You may need to install the XCode "
              "command line developer tools from the Mac App Store. "
              "(with --required-files={req}, --install-prefix={pfx})"
              .format(path=file_path, req=self._required_files, pfx=self._install_prefix))

  @memoized_method
  def path_entries(self):
    self._check_executables_exist()
    return [os.path.join(self._install_prefix, 'bin')]

  def _verify_tool_name(self, name):
    # TODO: introduce some more generic way to do this that can be applied to
    # provided tools as well, and actually checks whether the file exists within
    # some set of PATH entries and is executable.
    known_tools = self._required_files['bin']
    if name in known_tools:
      return name
    raise self.XCodeToolsInvalid(
      "Internal error: {!r} is not a valid tool. Known tools are: {!r}."
      .format(name, known_tools))

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
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename=self._verify_tool_name('clang'),
      library_dirs=[self._lib_dir],
      include_dirs=self._include_search_dirs)

  @memoized_method
  def cpp_compiler(self):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename=self._verify_tool_name('clang++'),
      library_dirs=[self._lib_dir],
      include_dirs=self._include_search_dirs)


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
