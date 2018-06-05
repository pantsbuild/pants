# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_binary import PythonBinary
from pants.base.exceptions import TargetDefinitionException
from pants_test.engine.sources_test_base import SourcesTestBase
from pants_test.test_base import TestBase


class TestPythonBinary(SourcesTestBase, TestBase):
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
    self.create_file('blork.py')
    blork_sources = self.sources_for(['blork.py'])

    assert self.make_target(spec=':binary1',
                            target_type=PythonBinary,
                            sources=blork_sources).entry_point == 'blork'

    self.create_dir('bin')
    self.create_file('bin/blork.py')
    bin_blork_sources = self.sources_for(['bin/blork.py'])

    assert self.make_target(spec=':binary2',
                            target_type=PythonBinary,
                            sources=bin_blork_sources).entry_point == 'bin.blork'

  def test_python_binary_with_entry_point_and_source(self):
    self.create_file('blork.py')
    blork_sources = self.sources_for(['blork.py'])

    assert 'blork' == self.make_target(spec=':binary1',
                                       target_type=PythonBinary,
                                       entry_point='blork',
                                       sources=blork_sources).entry_point
    assert 'blork:main' == self.make_target(spec=':binary2',
                                            target_type=PythonBinary,
                                            entry_point='blork:main',
                                            sources=blork_sources).entry_point

    self.create_dir('bin')
    self.create_file('bin/blork.py')
    bin_blork_sources = self.sources_for(['bin/blork.py'])

    assert 'bin.blork:main' == self.make_target(spec=':binary3',
                                                target_type=PythonBinary,
                                                entry_point='bin.blork:main',
                                                sources=bin_blork_sources).entry_point

  def test_python_binary_with_entry_point_and_source_mismatch(self):
    self.create_file('hork.py')

    hork_sources = self.sources_for(['hork.py'])

    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary1',
                       target_type=PythonBinary,
                       entry_point='blork',
                       sources=hork_sources)
    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary2',
                       target_type=PythonBinary,
                       entry_point='blork:main',
                       sources=hork_sources)
    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary3',
                       target_type=PythonBinary,
                       entry_point='bin.hork',
                       sources=hork_sources)
    with self.assertRaises(TargetDefinitionException):
      self.make_target(spec=':binary4',
                       target_type=PythonBinary,
                       entry_point='hork.blork',
                       sources=hork_sources)
