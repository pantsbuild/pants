# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.osutil import OS_ALIASES, known_os_names, normalize_os_name
from pants_test.base_test import BaseTest


class OsutilTest(BaseTest):

  def test_alias_normalization(self):
    for normal_os, aliases in OS_ALIASES.items():
      for alias in aliases:
        self.assertEqual(normal_os, normalize_os_name(alias))

  def test_keys_in_aliases(self):
    for key in OS_ALIASES.keys():
      self.assertIn(key, known_os_names())

  def test_no_warnings_on_known_names(self):
    for name in known_os_names():
      with self.captured_logging() as captured:
        normalize_os_name(name)
        self.assertEqual(0, len(captured.warnings()),
                         'Recieved unexpected warnings: {}'.format(captured.warnings()))

  def test_warnings_on_unknown_names(self):
    name = 'I really hope no one ever names an operating system with this string.'
    with self.captured_logging() as captured:
      normalize_os_name(name)
      self.assertEqual(1, len(captured.warnings()),
                       'Expected exactly one warning, but got: {}'.format(captured.warnings()))
