# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import TaskBase
from pants.backend.core.tasks.test_task_mixin import TestTaskMixin
from pants_test.tasks.task_test_base import TaskTestBase


class TestTaskMixinTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    class TestTaskMixinTask(TestTaskMixin, TaskBase):
      call_list = []

      def execute(self):
        super(TestTaskMixinTask, self).execute()

      def _execute(self, targets):
        self.call_list.append(['_execute', targets])

      def _get_targets(self):
        self.call_list.append(['_get_targets'])
        return ['targetA', 'targetB']

      def _validate_targets(self, targets):
        self.call_list.append(['_validate_targets', targets])

    return TestTaskMixinTask

  def test_execute_normal(self):
    self.task = self.create_task(self.context())

    self.task.execute()

    # Confirm that everything ran as expected
    self.assertIn(['_get_targets'], self.task.call_list)
    self.assertIn(['_validate_targets', ['targetA', 'targetB']], self.task.call_list)
    self.assertIn(['_execute', ['targetA', 'targetB']], self.task.call_list)

    print(self.task.call_list)

  def test_execute_skip(self):
    # Set the skip option
    self.set_options(skip=True)
    self.task = self.create_task(self.context())
    self.task.execute()

    # Ensure nothing got called
    self.assertListEqual(self.task.call_list, [])
