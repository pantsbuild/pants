# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Platform
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.collections import assert_single_element
from pants.util.memo import memoized_method


class GCC(NativeTool):
  options_scope = 'gcc'
  default_version = '7.3.0'
  archive_type = 'tgz'

  @memoized_method
  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  class GCCResourceLocationError(Exception): pass

  def _get_check_single_path_by_glob(self, *components):
    """Assert that the path components (which are joined into a glob) match exactly one path.

    The matched path may be a file or a directory. This method is used to avoid having to guess
    platform-specific intermediate directory names, e.g. 'x86_64-linux-gnu' or
    'x86_64-apple-darwin17.5.0'."""
    glob_path_string = os.path.join(*components)
    expanded_glob = glob.glob(glob_path_string)

    try:
      return assert_single_element(expanded_glob)
    except StopIteration as e:
      raise self.GCCResourceLocationError(
        "No elements for glob '{}' -- expected exactly one."
        .format(glob_path_string),
        e)
    except ValueError as e:
      raise self.GCCResourceLocationError(
        "Should have exactly one path matching expansion of glob '{}'."
        .format(glob_path_string),
        e)

  @memoized_method
  def _common_lib_dirs(self, platform):
    return [
      os.path.join(self.select(), 'lib'),
      os.path.join(self.select(), 'lib64'),
      os.path.join(self.select(), 'lib/gcc'),
      self._get_check_single_path_by_glob(
        self.select(), 'lib/gcc/*', self.version()),
    ]

  @memoized_method
  def _common_include_dirs(self, platform):
    return [
      os.path.join(self.select(), 'include'),
      self._get_check_single_path_by_glob(
        self.select(), 'lib/gcc/*', self.version(), 'include'),
    ]

  def c_compiler(self, platform):
    return CCompiler(
      path_entries=self.path_entries(),
      exe_filename='gcc',
      library_dirs=self._common_lib_dirs(platform),
      include_dirs=self._common_include_dirs(platform),
      extra_args=[])

  @memoized_method
  def _cpp_include_dirs(self, platform):
    # FIXME: explain why this is necessary!
    cpp_config_header_path = self._get_check_single_path_by_glob(
      self.select(), 'include/c++', self.version(), '*/bits/c++config.h')
    return [
      os.path.join(self.select(), 'include/c++', self.version()),
      # Get the directory that makes `#include <bits/c++config.h>` work.
      os.path.dirname(os.path.dirname(cpp_config_header_path)),
    ]

  def cpp_compiler(self, platform):
    return CppCompiler(
      path_entries=self.path_entries(),
      exe_filename='g++',
      library_dirs=self._common_lib_dirs(platform),
      include_dirs=(self._common_include_dirs(platform) + self._cpp_include_dirs(platform)),
      extra_args=[])


@rule(CCompiler, [Select(GCC), Select(Platform)])
def get_gcc(gcc, platform):
  return gcc.c_compiler(platform)


@rule(CppCompiler, [Select(GCC), Select(Platform)])
def get_gplusplus(gcc, platform):
  return gcc.cpp_compiler(platform)


def create_gcc_rules():
  return [
    get_gcc,
    get_gplusplus,
    RootRule(GCC),
  ]
