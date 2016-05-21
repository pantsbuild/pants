# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import os
import unittest

from pants.util.dirutil import safe_mkdtemp
from pants_test.option.util.fakes import create_options

from pants.contrib.python.checks.tasks.checkstyle.common import Nit, PythonFile


class CheckstylePluginTestBase(unittest.TestCase):
  plugin_type = None   # Subclasses must override.

  @property
  def file_required(self):
    """Override and return `True` if the plugin needs to operate on a file on disk."""
    return False

  def create_python_file(self, file_content):
    if self.file_required:
      tmpdir = safe_mkdtemp()
      with open(os.path.join(tmpdir, 'file.py'), 'wb') as fp:
        fp.write(file_content)
        fp.close()
        return PythonFile.parse(fp.name)
    else:
      return PythonFile.from_statement(file_content)

  def get_plugin(self, file_content, **options):
    python_file = self.create_python_file(file_content)
    full_options = copy.copy(options)
    full_options['skip'] = False
    options_object = create_options({'foo': full_options}).for_scope('foo')
    return self.plugin_type(options_object, python_file)

  def assertNit(self, file_content, expected_code, expected_severity=Nit.ERROR,
                expected_line_number=None):
    plugin = self.get_plugin(file_content)
    nits = list(plugin.nits())
    self.assertEqual(1, len(nits), 'Expected single nit, got: {}'.format(nits))
    nit = nits[0]
    self.assertEqual(expected_code, nit.code)
    self.assertEqual(expected_severity, nit.severity)
    if expected_line_number is not None:
      self.assertEqual(expected_line_number, nit.line_number)
    return nit

  def assertNoNits(self, file_content):
    plugin = self.get_plugin(file_content)
    nits = list(plugin.nits())
    self.assertEqual([], nits)
