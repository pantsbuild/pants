# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.util.osutil import (OS_ALIASES, get_closest_mac_host_platform_pair, known_os_names,
                               normalize_os_name)
from pants_test.test_base import TestBase


class OsutilTest(TestBase):

  def test_alias_normalization(self):
    for normal_os, aliases in OS_ALIASES.items():
      for alias in aliases:
        self.assertEqual(normal_os, normalize_os_name(alias))

  def test_keys_in_aliases(self):
    for key in OS_ALIASES.keys():
      self.assertIn(key, known_os_names())

  def test_no_warnings_on_known_names(self):
    for name in known_os_names():
      with self.captured_logging(logging.WARNING) as captured:
        normalize_os_name(name)
        self.assertEqual(0, len(captured.warnings()),
                         'Recieved unexpected warnings: {}'.format(captured.warnings()))

  def test_warnings_on_unknown_names(self):
    name = 'I really hope no one ever names an operating system with this string.'
    with self.captured_logging(logging.WARNING) as captured:
      normalize_os_name(name)
      self.assertEqual(1, len(captured.warnings()),
                       'Expected exactly one warning, but got: {}'.format(captured.warnings()))

  def test_get_closest_mac_host_platform_pair(self):
    # Note the gaps in darwin versions.
    platform_name_map = {
      ('linux', 'x86_64'): ('linux', 'x86_64'),
      ('linux', 'amd64'): ('linux', 'x86_64'),
      ('darwin', '10'): ('mac', '10.6'),
      ('darwin', '13'): ('mac', '10.9'),
      ('darwin', '14'): ('mac', '10.10'),
      ('darwin', '16'): ('mac', '10.12'),
      ('darwin', '17'): ('mac', '10.13'),
    }

    def get_macos_version(darwin_version):
      host, version = get_closest_mac_host_platform_pair(
        darwin_version, platform_name_map=platform_name_map)
      if host is not None:
        self.assertEqual('mac', host)
      return version

    self.assertEqual('10.13', get_macos_version('19'))
    self.assertEqual('10.13', get_macos_version('18'))
    self.assertEqual('10.13', get_macos_version('17'))
    self.assertEqual('10.12', get_macos_version('16'))
    self.assertEqual('10.10', get_macos_version('15'))
    self.assertEqual('10.10', get_macos_version('14'))
    self.assertEqual('10.9', get_macos_version('13'))
    self.assertEqual('10.6', get_macos_version('12'))
    self.assertEqual('10.6', get_macos_version('11'))
    self.assertEqual('10.6', get_macos_version('10'))
    self.assertEqual(None, get_macos_version('9'))
