# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.pyflakes import PyflakesChecker


class PyflakesCheckerTest(CheckstylePluginTestBase):
  plugin_type = PyflakesChecker

  def get_plugin(self, file_content, **options):
    return super(PyflakesCheckerTest, self).get_plugin(file_content,
                                                       ignore=options.get('ignore') or [])

  def test_pyflakes(self):
    self.assertNoNits('')

  def test_pyflakes_unused_import(self):
    self.assertNit('import os', 'F401', expected_line_number='001')

  def test_pyflakes_ignore(self):
    plugin = self.get_plugin('import os', ignore=['F401'])
    self.assertEqual([], list(plugin.nits()))
