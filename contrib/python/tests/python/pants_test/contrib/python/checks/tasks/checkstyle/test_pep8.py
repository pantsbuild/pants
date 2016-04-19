# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.pep8 import PEP8Checker


class PEP8CheckerTest(CheckstylePluginTestBase):
  plugin_type = PEP8Checker

  @property
  def file_required(self):
    return True

  def get_plugin(self, file_content, **options):
    return super(PEP8CheckerTest, self).get_plugin(file_content,
                                                   max_length=options.get('max_length', 10),
                                                   ignore=options.get('ignore', False))

  def test_pep8(self):
    self.assertNoNits('')

  def test_pep8_line_length(self):
    self.assertNit('# Longer than 10.\n', 'E501', expected_line_number='001')
