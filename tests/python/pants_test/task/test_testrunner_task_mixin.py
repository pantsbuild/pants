# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections

from mock import patch

from pants.base.exceptions import TestFailedTaskError
from pants.task.task import TaskBase
from pants.task.testrunner_task_mixin import TestRunnerTaskMixin
from pants.util.process_handler import ProcessHandler
from pants.util.timeout import TimeoutReached
from pants_test.tasks.task_test_base import TaskTestBase


class DummyTestTarget(object):
  def __init__(self, name, timeout=None):
    self.name = name
    self.timeout = timeout
    self.address = collections.namedtuple('address', ['spec'])(name)

targetA = DummyTestTarget('TargetA')
targetB = DummyTestTarget('TargetB', timeout=1)
targetC = DummyTestTarget('TargetC', timeout=10)


class TestRunnerTaskMixinTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    class TestRunnerTaskMixinTask(TestRunnerTaskMixin, TaskBase):
      call_list = []

      def _execute(self, all_targets):
        self.call_list.append(['_execute', all_targets])
        self._spawn_and_wait()

      def _spawn(self, *args, **kwargs):
        self.call_list.append(['_spawn', args, kwargs])

        class FakeProcessHandler(ProcessHandler):
          def wait(_):
            self.call_list.append(['process_handler.wait'])
            return 0

          def kill(_):
            self.call_list.append(['process_handler.kill'])

          def terminate(_):
            self.call_list.append(['process_handler.terminate'])

          def poll(_):
            self.call_list.append(['process_handler.poll'])

        return FakeProcessHandler()

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

    return TestRunnerTaskMixinTask

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

  def test_get_timeouts_with_default(self):
    """If there is a default timeout, use that for targets which have no timeout set."""

    self.set_options(timeouts=True, timeout_default=2)
    task = self.create_task(self.context())

    self.assertEquals(task._timeout_for_targets([targetA, targetB]), 3)

  def test_get_timeouts_with_maximum(self):
    """If a timeout exceeds the maximum, set it to that."""

    self.set_options(timeouts=True, timeout_maximum=1)
    task = self.create_task(self.context())
    self.assertEquals(task._timeout_for_targets([targetC]), 1)

  def test_default_maximum_conflict(self):
    """If the default exceeds the maximum, throw an error."""

    self.set_options(timeouts=True, timeout_maximum=1, timeout_default=10)
    task = self.create_task(self.context())
    with self.assertRaises(TestFailedTaskError):
      task.execute()


class TestRunnerTaskMixinSimpleTimeoutTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    class TestRunnerTaskMixinTask(TestRunnerTaskMixin, TaskBase):
      call_list = []

      def _execute(self, all_targets):
        self.call_list.append(['_execute', all_targets])
        self._spawn_and_wait()

      def _spawn(self, *args, **kwargs):
        self.call_list.append(['_spawn', args, kwargs])

        class FakeProcessHandler(ProcessHandler):
          def wait(_):
            self.call_list.append(['process_handler.wait'])
            return 0

          def kill(_):
            self.call_list.append(['process_handler.kill'])

          def terminate(_):
            self.call_list.append(['process_handler.terminate'])

          def poll(_):
            self.call_list.append(['process_handler.poll'])
            return 0

        return FakeProcessHandler()

      def _get_targets(self):
        return [targetB]

      def _test_target_filter(self):
        def target_filter(target):
          return True

        return target_filter

      def _validate_target(self, target):
        self.call_list.append(['_validate_target', target])

    return TestRunnerTaskMixinTask

  def test_timeout(self):
    self.set_options(timeouts=True)
    task = self.create_task(self.context())

    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      mock_timeout().__exit__.side_effect = TimeoutReached(1)

      with self.assertRaises(TestFailedTaskError):
        task.execute()

      # Ensures that Timeout is instantiated with a 1 second timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (1,))

  def test_timeout_disabled(self):
    self.set_options(timeouts=False)
    task = self.create_task(self.context())

    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      task.execute()

      # Ensures that Timeout is instantiated with no timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (None,))


class TestRunnerTaskMixinGracefulTimeoutTest(TaskTestBase):

  def create_process_handler(self, return_none_first=True):
    class FakeProcessHandler(ProcessHandler):
      call_list = []
      poll_called = False

      def wait(self):
        self.call_list.append(['process_handler.wait'])
        return 0

      def kill(self):
        self.call_list.append(['process_handler.kill'])

      def terminate(self):
        self.call_list.append(['process_handler.terminate'])

      def poll(self):
        print("poll called")
        self.call_list.append(['process_handler.poll'])
        if not self.poll_called and return_none_first:
          self.poll_called = True
          return None
        else:
          return 0

    return FakeProcessHandler()

  def task_type(cls):
    class TestRunnerTaskMixinTask(TestRunnerTaskMixin, TaskBase):
      call_list = []

      def _execute(self, all_targets):
        self.call_list.append(['_execute', all_targets])
        self._spawn_and_wait()

      def _spawn(self, *args, **kwargs):
        self.call_list.append(['_spawn', args, kwargs])

        return cls.process_handler

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

    return TestRunnerTaskMixinTask

  def test_graceful_terminate_if_poll_is_none(self):
    self.process_handler = self.create_process_handler(return_none_first=True)

    self.set_options(timeouts=True)
    task = self.create_task(self.context())

    with patch('pants.task.testrunner_task_mixin.Timer') as mock_timer:
      def set_handler(dummy, handler):
        mock_timer_instance = mock_timer.return_value
        mock_timer_instance.start.side_effect = handler
        return mock_timer_instance

      mock_timer.side_effect = set_handler


      with self.assertRaises(TestFailedTaskError):
        task.execute()

      # Ensure that all the calls we want to kill the process gracefully are made.
      self.assertEqual(self.process_handler.call_list,
                       [[u'process_handler.terminate'], [u'process_handler.poll'], [u'process_handler.kill'], [u'process_handler.wait']])

  def test_graceful_terminate_if_poll_is_zero(self):
    self.process_handler = self.create_process_handler(return_none_first=False)

    self.set_options(timeouts=True)
    task = self.create_task(self.context())

    with patch('pants.task.testrunner_task_mixin.Timer') as mock_timer:
      def set_handler(dummy, handler):
        mock_timer_instance = mock_timer.return_value
        mock_timer_instance.start.side_effect = handler
        return mock_timer_instance

      mock_timer.side_effect = set_handler


      with self.assertRaises(TestFailedTaskError):
        task.execute()

      # Ensure that we only call terminate, and not kill.
      self.assertEqual(self.process_handler.call_list,
                       [[u'process_handler.terminate'], [u'process_handler.poll'], [u'process_handler.wait']])


class TestRunnerTaskMixinMultipleTargets(TaskTestBase):

  @classmethod
  def task_type(cls):
    class TestRunnerTaskMixinMultipleTargetsTask(TestRunnerTaskMixin, TaskBase):
      def _execute(self, all_targets):
        self._spawn_and_wait()

      def _spawn(self, *args, **kwargs):
        class FakeProcessHandler(ProcessHandler):
          def wait(self):
            return 0

          def kill(self):
            pass

          def terminate(self):
            pass

          def poll(self):
            pass

        return FakeProcessHandler()

      def _test_target_filter(self):
        return lambda target: True

      def _validate_target(self, target):
        pass

      def _get_targets(self):
        return [targetA, targetB]

      def _get_test_targets_for_spawn(self):
        return self.current_targets

    return TestRunnerTaskMixinMultipleTargetsTask

  def test_multiple_targets_single_target_timeout(self):
    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      mock_timeout().__exit__.side_effect = TimeoutReached(1)

      self.set_options(timeouts=True)
      task = self.create_task(self.context())

      task.current_targets = [targetA]
      with self.assertRaises(TestFailedTaskError) as cm:
        task.execute()
      self.assertEqual(len(cm.exception.failed_targets), 1)
      self.assertEqual(cm.exception.failed_targets[0].address.spec, 'TargetA')

      task.current_targets = [targetB]
      with self.assertRaises(TestFailedTaskError) as cm:
        task.execute()
      self.assertEqual(len(cm.exception.failed_targets), 1)
      self.assertEqual(cm.exception.failed_targets[0].address.spec, 'TargetB')
