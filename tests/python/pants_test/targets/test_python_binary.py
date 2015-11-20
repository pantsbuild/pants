# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pytest

from pants.backend.python.targets.python_binary import PythonBinary
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class TestPythonBinary(BaseTest):
  def setUp(self):
    super(TestPythonBinary, self).setUp()
    # Force creation of SourceRootConfig global instance. PythonBinary uses source roots
    # when computing entry points.
    self.context()

  def test_python_binary_must_have_some_entry_point(self):
    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary', target_type=PythonBinary)

  def test_python_binary_with_entry_point_no_source(self):
    assert self.make_target(spec=':binary',
                            target_type=PythonBinary,
                            entry_point='blork').entry_point == 'blork'

  def test_python_binary_with_source_no_entry_point(self):
    assert self.make_target(spec=':binary1',
                            target_type=PythonBinary,
                            source='blork.py').entry_point == 'blork'
    assert self.make_target(spec=':binary2',
                            target_type=PythonBinary,
                            source='bin/blork.py').entry_point == 'bin.blork'

  def test_python_binary_with_entry_point_and_source(self):
    assert 'blork' == self.make_target(spec=':binary1',
                                       target_type=PythonBinary,
                                       entry_point='blork',
                                       source='blork.py').entry_point
    assert 'blork:main' == self.make_target(spec=':binary2',
                                            target_type=PythonBinary,
                                            entry_point='blork:main',
                                            source='blork.py').entry_point
    assert 'bin.blork:main' == self.make_target(spec=':binary3',
                                                target_type=PythonBinary,
                                                entry_point='bin.blork:main',
                                                source='bin/blork.py').entry_point

  def test_python_binary_with_entry_point_and_source_mismatch(self):
    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary1',
                       target_type=PythonBinary,
                       entry_point='blork',
                       source='hork.py')
    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary2',
                       target_type=PythonBinary,
                       entry_point='blork:main',
                       source='hork.py')
    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary3',
                       target_type=PythonBinary,
                       entry_point='bin.blork',
                       source='blork.py')
    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary4',
                       target_type=PythonBinary,
                       entry_point='bin.blork',
                       source='bin.py')
