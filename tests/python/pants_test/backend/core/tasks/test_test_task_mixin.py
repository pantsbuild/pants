# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from mock import patch

from pants.backend.core.tasks.test_task_mixin import TestTaskMixin
from pants.base.exceptions import TestFailedTaskError
from pants.task.task import TaskBase
from pants.util.timeout import TimeoutReached
from pants_test.tasks.task_test_base import TaskTestBase


class DummyTestTarget(object):
  def __init__(self, name, timeout=None):
    self.name = name
    self.timeout = timeout

targetA = DummyTestTarget('TargetA')
targetB = DummyTestTarget('TargetB', timeout=1)


class TestTaskMixinTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    class TestTaskMixinTask(TestTaskMixin, TaskBase):
      call_list = []

      def _execute(self, all_targets):
        self.call_list.append(['_execute', all_targets])

      def _get_targets(self):
        return [targetA, targetB]

      def _test_target_filter(self):
        def target_filter(target):
          self.call_list.append(['target_filter', target])
          if target.name == 'TargetA':
            return False
          else:
            return True

        return target_filter

      def _validate_target(self, target):
        self.call_list.append(['_validate_target', target])

      def _timeout_abort_handler(self):
        self.call_list.append(['_timeout_abort_handler'])

    return TestTaskMixinTask

  def test_execute_normal(self):
    task = self.create_task(self.context())

    task.execute()

    # Confirm that everything ran as expected
    self.assertIn(['target_filter', targetA], task.call_list)
    self.assertIn(['target_filter', targetB], task.call_list)
    self.assertIn(['_validate_target', targetB], task.call_list)
    self.assertIn(['_execute', [targetA, targetB]], task.call_list)

  def test_execute_skip(self):
    # Set the skip option
    self.set_options(skip=True)
    task = self.create_task(self.context())
    task.execute()

    # Ensure nothing got called
    self.assertListEqual(task.call_list, [])

  def test_get_timeouts_no_default(self):
    """If there is no default and one of the targets has no timeout, then there is no timeout for the entire run."""

    self.set_options(timeouts=True, timeout_default=None)
    task = self.create_task(self.context())

    self.assertIsNone(task._timeout_for_targets([targetA, targetB]))

  def test_get_timeouts_disabled(self):
    """If timeouts are disabled, there is no timeout for the entire run."""

    self.set_options(timeouts=False, timeout_default=2)
    task = self.create_task(self.context())

    self.assertIsNone(task._timeout_for_targets([targetA, targetB]))

  def test_get_timeouts_w_default(self):
    """If there is a default timeout, use that for targets which have no timeout set."""

    self.set_options(timeouts=True, timeout_default=2)
    task = self.create_task(self.context())

    self.assertEquals(task._timeout_for_targets([targetA, targetB]), 3)


class TestTaskMixinTimeoutTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    class TestTaskMixinTask(TestTaskMixin, TaskBase):
      call_list = []

      def _execute(self, all_targets):
        self.call_list.append(['_execute', all_targets])

      def _get_targets(self):
        return [targetB]

      def _test_target_filter(self):
        def target_filter(target):
          return True

        return target_filter

      def _validate_target(self, target):
        self.call_list.append(['_validate_target', target])

    return TestTaskMixinTask

  def test_timeout(self):
    self.set_options(timeouts=True)
    task = self.create_task(self.context())

    with patch('pants.backend.core.tasks.test_task_mixin.Timeout') as mock_timeout:
      mock_timeout().__exit__.side_effect = TimeoutReached(1)

      with self.assertRaises(TestFailedTaskError):
        task.execute()

      # Ensures that Timeout is instantiated with a 1 second timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (1,))

  def test_timeout_disabled(self):
    self.set_options(timeouts=False)
    task = self.create_task(self.context())

    with patch('pants.backend.core.tasks.test_task_mixin.Timeout') as mock_timeout:
      task.execute()

      # Ensures that Timeout is instantiated with no timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (None,))
