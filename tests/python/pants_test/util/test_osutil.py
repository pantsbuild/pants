# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import unittest
from contextlib import contextmanager

from pants.util.osutil import OS_ALIASES, known_os_names, normalize_os_name


class OsutilTest(unittest.TestCase):

  class WarningRecorder(object):
    """Simple logging handler to record warnings."""

    def __init__(self):
      self.warning_list = []
      self.level = logging.WARNING

    def handle(self, record):
      self.warning_list.append('{}: {}'.format(record.name, record.getMessage()))

  @contextmanager
  def warnings(self):
    handler = self.WarningRecorder()
    logging.getLogger('').addHandler(handler)
    yield handler.warning_list

  def test_alias_normalization(self):
    for normal_os, aliases in OS_ALIASES.items():
      for alias in aliases:
        self.assertEqual(normal_os, normalize_os_name(alias))

  def test_keys_in_aliases(self):
    for key in OS_ALIASES.keys():
      self.assertIn(key, known_os_names())

  def test_no_warnings_on_known_names(self):
    for name in known_os_names():
      with self.warnings() as warning_list:
        normalize_os_name(name)
        self.assertEqual(0, len(warning_list),
                         'Recieved unexpected warnings: {}'.format(warning_list))

  def test_warnings_on_unknown_names(self):
    name = 'I really hope no one ever names an operating system with this string.'
    with self.warnings() as warning_list:
      normalize_os_name(name)
      self.assertEqual(1, len(warning_list),
                       'Expected exactly one warning, but got: {}'.format(warning_list))
