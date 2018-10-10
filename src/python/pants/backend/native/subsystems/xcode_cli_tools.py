# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.config.environment import Assembler, CCompiler, CppCompiler, Linker
from pants.engine.rules import rule
from pants.engine.selectors import Select
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_readable_dir
from pants.util.memo import memoized_method, memoized_property


MIN_OSX_SUPPORTED_VERSION = '10.11'


MIN_OSX_VERSION_ARG = '-mmacosx-version-min={}'.format(MIN_OSX_SUPPORTED_VERSION)


class XCodeCLITools(Subsystem):
  """Subsystem to detect and provide the XCode command line developer tools.

  This subsystem exists to give a useful error message if the tools aren't
  installed, and because the install location may not be on the PATH when Pants
  is invoked.
  """

  options_scope = 'xcode-cli-tools'

  _REQUIRED_FILES = {
    'bin': [
      'as',
      'cc',
      'c++',
      'clang',
      'clang++',
      'ld',
      'lipo',
    ],
    # Any of the entries that would be here are not directly below the 'include' or 'lib' dirs, and
    # we haven't yet encountered an invalid XCode/CLI tools installation which has the include dirs,
    # but incorrect files. These would need to be updated if such an issue arises.
    'include': [],
    'lib': [],
  }

  INSTALL_PREFIXES_DEFAULT = [
    # Prefer files from this installation directory, if available. This doesn't appear to be
    # populated with e.g. header files on travis.
    '/usr',
    # Populated by the XCode CLI tools.
    '/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr',
    # Populated by the XCode app. These are derived from using the -v or -H switches invoking the
    # osx clang compiler.
    '/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr',
    '/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/clang/9.1.0',
    '/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk/usr',
  ]

  class XCodeToolsUnavailable(Exception):
    """Thrown if the XCode CLI tools could not be located."""

  class XCodeToolsInvalid(Exception):
    """Thrown if a method within this subsystem requests a nonexistent tool."""

  @classmethod
  def register_options(cls, register):
    super(XCodeCLITools, cls).register_options(register)

    register('--install-prefixes', type=list, default=cls.INSTALL_PREFIXES_DEFAULT,
             fingerprint=True, advanced=True,
             help='Locations to search for resources from the XCode CLI tools, including a '
                  'compiler, linker, header files, and some libraries. '
                  'Under this directory should be some selection of these subdirectories: {}.'
                  .format(cls._REQUIRED_FILES.keys()))

  @memoized_property
  def _all_existing_install_prefixes(self):
    return [pfx for pfx in self.get_options().install_prefixes if is_readable_dir(pfx)]

  # NB: We use @memoized_method in this file for methods which may raise.
  @memoized_method
  def _get_existing_subdirs(self, subdir_name):
    maybe_subdirs = [os.path.join(pfx, subdir_name) for pfx in self._all_existing_install_prefixes]
    existing_dirs = [existing_dir for existing_dir in maybe_subdirs if is_readable_dir(existing_dir)]

    required_files_for_dir = self._REQUIRED_FILES.get(subdir_name)
    if required_files_for_dir:
      for fname in required_files_for_dir:
        found = False
        for subdir in existing_dirs:
          full_path = os.path.join(subdir, fname)
          if os.path.isfile(full_path):
            found = True
            continue

        if not found:
          raise self.XCodeToolsUnavailable(
            "File '{fname}' in subdirectory '{subdir_name}' does not exist at any of the specified "
            "prefixes. This file is required to build native code on this platform. You may need "
            "to install the XCode command line developer tools from the Mac App Store.\n\n"
            "If the XCode tools are installed and you are still seeing this message, please file "
            "an issue at https://github.com/pantsbuild/pants/issues/new describing your "
            "OSX environment and which file could not be found.\n"
            "The existing install prefixes were: {pfxs}. These can be extended with "
            "--{scope}-install-prefixes."
            .format(fname=fname,
                    subdir_name=subdir_name,
                    pfxs=self._all_existing_install_prefixes,
                    scope=self.get_options_scope_equivalent_flag_component()))

    return existing_dirs

  @memoized_method
  def path_entries(self):
    return self._get_existing_subdirs('bin')

  @memoized_method
  def lib_dirs(self):
    return self._get_existing_subdirs('lib')

  @memoized_method
  def include_dirs(self):
    base_inc_dirs = self._get_existing_subdirs('include')

    all_inc_dirs = base_inc_dirs
    for d in base_inc_dirs:
      # TODO: figure out what this directory does and why it's not already found by this compiler.
      secure_inc_dir = os.path.join(d, 'secure')
      if is_readable_dir(secure_inc_dir):
        all_inc_dirs.append(secure_inc_dir)

    return all_inc_dirs

  @memoized_method
  def assembler(self):
    return Assembler(
      path_entries=self.path_entries(),
      exe_filename='as',
      library_dirs=[])

  @memoized_method
  def linker(self):
    return Linker(
      path_entries=self.path_entries(),
      exe_filename='ld',
      library_dirs=[],
      linking_library_dirs=[],
      extra_args=[MIN_OSX_VERSION_ARG])

  @memoized_method
  def c_compiler(self):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang',
      library_dirs=self.lib_dirs(),
      include_dirs=self.include_dirs(),
      extra_args=[MIN_OSX_VERSION_ARG])

  @memoized_method
  def cpp_compiler(self):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='clang++',
      library_dirs=self.lib_dirs(),
      include_dirs=self.include_dirs(),
      extra_args=[MIN_OSX_VERSION_ARG])


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
  ]
