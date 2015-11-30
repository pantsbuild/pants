# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import unittest

from pants_test.option.util.fakes import create_options

from pants.contrib.python.checks.tasks.checkstyle.common import Nit, PythonFile


class CheckstylePluginTestBase(unittest.TestCase):
  plugin_type = None   # Subclasses must override.

  def get_plugin(self, file_content, **options):
    python_file = PythonFile.from_statement(file_content)
    full_options = copy.copy(options)
    full_options['skip'] = False
    options_object = create_options({'foo': full_options}).for_scope('foo')
    return self.plugin_type(options_object, python_file)

  def assertNit(self, file_content, expected_code, expected_severity=Nit.ERROR,
                expected_line_number=None):
    plugin = self.get_plugin(file_content)
    nits = list(plugin.nits())
    self.assertEqual(1, len(nits), 'Expected single nit, got: {}'.format(nits))
    self.assertEqual(expected_code, nits[0].code)
    self.assertEqual(expected_severity, nits[0].severity)
    if expected_line_number is not None:
      self.assertEqual(expected_line_number, nits[0]._line_number)

  def assertNoNits(self, file_content):
    plugin = self.get_plugin(file_content)
    nits = list(plugin.nits())
    self.assertEqual([], nits)
