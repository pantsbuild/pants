# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler
from pants.backend.native.subsystems.utils.archive_file_mapper import ArchiveFileMapper
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.memo import memoized_property


class GCC(NativeTool):
  """Subsystem wrapping an archive providing a GCC distribution.

  This subsystem provides the gcc and g++ compilers.

  NB: The lib and include dirs provided by this distribution are produced by using known relative
  paths into the distribution of GCC provided on Pantsbuild S3. If we change how we distribute GCC,
  these methods may have to change. They should be stable to version upgrades, however.
  """
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  @classmethod
  def subsystem_dependencies(cls):
    return super(GCC, cls).subsystem_dependencies() + (ArchiveFileMapper.scoped(cls),)

  @memoized_property
  def _file_mapper(self):
    return ArchiveFileMapper.scoped_instance(self)

  def _filemap(self, all_components_list):
    return self._file_mapper.map_files(self.select(), all_components_list)

  @memoized_property
  def path_entries(self):
    return self._filemap([('bin',)])

  @memoized_property
  def _common_lib_dirs(self):
    return self._filemap([
      ('lib',),
      ('lib64',),
      ('lib/gcc',),
      ('lib/gcc/*', self.version()),
    ])

  @memoized_property
  def _common_include_dirs(self):
    return self._filemap([
      ('include',),
      ('lib/gcc/*', self.version(), 'include'),
    ])

  def c_compiler(self):
    return CCompiler(
      path_entries=self.path_entries,
      exe_filename='gcc',
      library_dirs=self._common_lib_dirs,
      include_dirs=self._common_include_dirs,
      extra_args=[])

  @memoized_property
  def _cpp_include_dirs(self):
    most_cpp_include_dirs = self._filemap([
      ('include/c++', self.version()),
    ])

    # This file is needed for C++ compilation.
    cpp_config_header_path = self._file_mapper.assert_single_path_by_glob(
      # NB: There are multiple paths matching this glob unless we provide the full path to
      # c++config.h, which is why we bypass self._filemap() here.
      [self.select(), 'include/c++', self.version(), '*/bits/c++config.h'])
    # Get the directory that makes `#include <bits/c++config.h>` work.
    plat_cpp_header_dir =  os.path.dirname(os.path.dirname(cpp_config_header_path))

    return most_cpp_include_dirs + [plat_cpp_header_dir]

  def cpp_compiler(self):
    return CppCompiler(
      path_entries=self.path_entries,
      exe_filename='g++',
      library_dirs=self._common_lib_dirs,
      include_dirs=(self._common_include_dirs + self._cpp_include_dirs),
      extra_args=[])


@rule(CCompiler, [Select(GCC)])
def get_gcc(gcc):
  return gcc.c_compiler()


@rule(CppCompiler, [Select(GCC)])
def get_gplusplus(gcc):
  return gcc.cpp_compiler()


def create_gcc_rules():
  return [
    get_gcc,
    get_gplusplus,
    RootRule(GCC),
  ]
