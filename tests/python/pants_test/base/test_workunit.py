# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import time
import unittest
from contextlib import contextmanager

from mock import Mock

from pants.base.workunit import WorkUnit
from pants.util.contextutil import temporary_dir


print('wut')
class WorkUnitTest(unittest.TestCase):

  # life cycle tests
  #
  # features
  #  - current duration
  #  - name
  #  - propagates outcome to parent
  #  - closed output not in output list
  #  - output value gathering
  #  - if parent, parent has current as child
  # what happens for outputs
  def test_duration_dynamic_when_not_ended(self):
    with self.mocked_time() as m_time:
      with temporary_dir() as rundir:
        m_time.return_value = 10.0
        wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')

        m_time.return_value = 20.0

        self.assertEqual(10.0, wu.duration())

        m_time.return_value = 30.0

        self.assertEqual(20.0, wu.duration())

  def test_duration_fixed_after_end(self):
    with self.mocked_time() as m_time:
      with temporary_dir() as rundir:
        m_time.return_value = 10.0
        wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')

        m_time.return_value = 20.0
        wu.end()

        self.assertEqual(10.0, wu.duration())

        m_time.return_value = 30.0

        self.assertEqual(10.0, wu.duration())

  def test_output_name_containing_non_identifier_char_not_allowed(self):
    with temporary_dir() as rundir:
      with self.assertRaises(Exception):
        wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')
        wu.output('some:colon')


  def test_end_closes_outputs(self):
    with temporary_dir() as rundir:
      wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')
      wu.output('someout')

      wu.end()

      self.assertTrue(wu.output('someout').is_closed())

  def test_full_output_contents_is_not_empty_if_end_already_called(self):
    with temporary_dir() as rundir:
      wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')
      wu.output('someout')

      wu.end()

      self.assertEqual({'someout': ''}, wu.full_outputs_contents())

  def test_full_output_contents_contains_already_read_values(self):
    with temporary_dir() as rundir:
      wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')
      some_out = wu.output('someout')

      some_out.write('abc')
      some_out.read() # abc
      some_out.write('def')

      self.assertEqual('abcdef', wu.full_outputs_contents()['someout'])

  def test_unread_outputs_contents_contains_only_unread_values(self):
    with temporary_dir() as rundir:
      wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')
      some_out = wu.output('someout')

      some_out.write('abc')
      some_out.read() # abc
      some_out.write('def')

      self.assertEqual('def', wu.unread_outputs_contents()['someout'])

  def test_unread_outputs_contents_empty_for_ended_workunit(self):
    with temporary_dir() as rundir:
      wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')
      some_out = wu.output('someout')

      some_out.write('abc')
      wu.end()

      self.assertEqual(0, len(wu.unread_outputs_contents()))

  def test_outcome_remains_unchanged_if_set_to_higher_value(self):
    with temporary_dir() as rundir:
      wu = WorkUnit(run_info_dir=rundir, parent=None, name='default')
      wu.set_outcome(WorkUnit.ABORTED)

      wu.set_outcome(WorkUnit.SUCCESS)

      self.assertEqual(WorkUnit.ABORTED, wu.outcome())

  def test_parent_outcome_remains_unchanged_if_child_set_to_higher_value(self):
    with temporary_dir() as rundir:
      parent = WorkUnit(run_info_dir=rundir, parent=None, name='parent')
      parent.set_outcome(WorkUnit.ABORTED)
      child = WorkUnit(run_info_dir=rundir, parent=parent, name='default')

      child.set_outcome(WorkUnit.SUCCESS)

      self.assertEqual(WorkUnit.ABORTED, parent.outcome())

  def test_child_outcome_propagated_to_parent_if_set_to_lower_value(self):
    with temporary_dir() as rundir:
      parent = WorkUnit(run_info_dir=rundir, parent=None, name='parent')
      child = WorkUnit(run_info_dir=rundir, parent=parent, name='default')

      child.set_outcome(WorkUnit.SUCCESS)

      self.assertEqual(WorkUnit.SUCCESS, parent.outcome())

  @contextmanager
  def mocked_time(self):
    old_time = time.time
    try:
      time.time = Mock()
      yield time.time
    finally:
      time.time = old_time
