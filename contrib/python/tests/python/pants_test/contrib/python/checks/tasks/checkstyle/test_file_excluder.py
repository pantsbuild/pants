# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import textwrap

from pants_test.base_test import BaseTest

from pants.contrib.python.checks.tasks.checkstyle.file_excluder import FileExcluder


logger = logging.getLogger(__name__)


class TestExcluder(BaseTest):

  def setUp(self):
    super(TestExcluder, self).setUp()
    excludes_text = textwrap.dedent("""
      # ignore C++
      .*\.cpp::.*

      # ignore python
      .*\.py::Flake8
    """)
    self.excluder = FileExcluder(
      self._create_scalastyle_excludes_file([excludes_text]),
      logger)

  def _create_scalastyle_excludes_file(self, exclude_patterns=None):
    return self.create_file(
      relpath='scalastyle_excludes.txt',
      contents='\n'.join(exclude_patterns) if exclude_patterns else '')

  def test_excludes_cpp_any(self):
    self.assertFalse(self.excluder.should_include('test/file.cpp', '.*'))

  def test_excludes_cpp_flake8(self):
    self.assertFalse(self.excluder.should_include('test/file.cpp', 'Flake8'))

  def test_excludes_python_flake8(self):
    self.assertFalse(self.excluder.should_include('test/file.py', 'Flake8'))

  def test_excludes_python_trailingws(self):
    self.assertTrue(self.excluder.should_include('test/file.py', 'TrailingWhiteSpace'))
