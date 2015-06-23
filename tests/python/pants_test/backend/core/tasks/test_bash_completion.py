# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.bash_completion import BashCompletionTask
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class BashCompletionTest(ConsoleTaskTestBase):

  @classmethod
  def task_type(cls):
    return BashCompletionTask

  def mocked_parse_all_tasks_and_help(self, _):
    return set(), '', set()

  # Override `execute_console_task()`, and mock out the `parse_all_tasks_and_help()` method.
  def execute_console_task(self, targets=None, extra_targets=None, options=None, workspace=None):
    options = options or {}
    self.set_options(**options)
    context = self.context(target_roots=targets, workspace=workspace)
    task = self.create_task(context)
    task.parse_all_tasks_and_help = self.mocked_parse_all_tasks_and_help
    return list(task.console_output(list(task.context.targets()) + list(extra_targets or ())))

  def test_bash_completion_loads_template(self):
    self.assert_console_output_contains("# Pants Autocompletion Support")
