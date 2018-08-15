# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.config.environment import Platform
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.utils.parse_search_dirs import ParseSearchDirs
from pants_test.backend.native.util.platform_utils import platform_specific
from pants_test.subsystem.subsystem_util import global_subsystem_instance, init_subsystems
from pants_test.test_base import TestBase


class TestLibcDirectorySearchFailure(TestBase):

  def setUp(self):
    init_subsystems([LibcDev], options={
      'libc': {
        'enable_libc_search': True,
        'libc_dir': '/does/not/exist',
      },
    })

    self.libc = global_subsystem_instance(LibcDev)
    self.platform = Platform.create()

  @platform_specific('linux')
  def test_libc_search_failure(self):
    with self.assertRaises(LibcDev.HostLibcDevResolutionError) as cm:
      self.libc.get_libc_dirs(self.platform)
    expected_msg = (
      "Could not locate crti.o in directory /does/not/exist provided by the --libc-dir option.")
    self.assertEqual(expected_msg, str(cm.exception))

  @platform_specific('darwin')
  def test_libc_search_noop_osx(self):
    self.assertEqual([], self.libc.get_libc_dirs(self.platform))


class TestLibcSearchDisabled(TestBase):

  def setUp(self):
    init_subsystems([LibcDev], options={
      'libc': {
        'enable_libc_search': False,
        'libc_dir': '/does/not/exist',
      },
    })

    self.libc = global_subsystem_instance(LibcDev)
    self.platform = Platform.create()

  @platform_specific('linux')
  def test_libc_disabled_search(self):
    self.assertEqual([], self.libc.get_libc_dirs(self.platform))


class TestLibcCompilerSearchFailure(TestBase):

  def setUp(self):
    init_subsystems([LibcDev], options={
      'libc': {
        'enable_libc_search': True,
        'host_compiler': 'this_executable_does_not_exist',
      },
    })

    self.libc = global_subsystem_instance(LibcDev)
    self.platform = Platform.create()

  @platform_specific('linux')
  def test_libc_compiler_search_failure(self):
    with self.assertRaises(ParseSearchDirs.ParseSearchDirsError) as cm:
      self.libc.get_libc_dirs(self.platform)
    expected_msg = (
      "Process invocation with argv "
      "'this_executable_does_not_exist -print-search-dirs' and environment None failed.")
    self.assertIn(expected_msg, str(cm.exception))
