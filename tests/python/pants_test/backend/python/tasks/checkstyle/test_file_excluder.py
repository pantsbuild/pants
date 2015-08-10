# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import textwrap

import pytest

from pants.backend.python.tasks.checkstyle.checker import PythonCheckStyleTask
from pants.backend.python.tasks.checkstyle.file_excluder import FileExcluder
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


logger = logging.getLogger(__name__)

class TestExcluder(PythonTaskTestBase):
  def task_type(cls):
    """Required method"""
    return PythonCheckStyleTask

  def setUp(self, *args, **kwargs):
    super(TestExcluder, self).setUp(*args, **kwargs)
    excludes_text = textwrap.dedent('''
      # ignore C++
      .*\.cpp::.*

      # ignore python
      .*\.py::Flake8''')
    self.excluder = FileExcluder(
      self._create_scalastyle_excludes_file([excludes_text]),
      logger)

  def _create_scalastyle_excludes_file(self, exclude_patterns=None):
    return self.create_file(
      relpath='scalastyle_excludes.txt',
      contents='\n'.join(exclude_patterns) if exclude_patterns else '')

  def test_excludes_cpp_any(self):
    assert not self.excluder.should_include('test/file.cpp', '.*')

  def test_excludes_cpp_flake8(self):
    assert not self.excluder.should_include('test/file.cpp', 'Flake8')

  def test_excludes_python_flake8(self):
    assert not self.excluder.should_include('test/file.py', 'Flake8')

  def test_excludes_python_trailingws(self):
    assert self.excluder.should_include('test/file.py', 'TrailingWhiteSpace')
