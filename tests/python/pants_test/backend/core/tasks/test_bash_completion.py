# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.bash_completion import BashCompletionTask
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class MockedBashCompletionTask(BashCompletionTask):
  """A version of the BashCompletionTask, with the goal/help parsing mocked out."""
  def parse_all_tasks_and_help(self, _):
    return set(), '', set()


class BashCompletionTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return MockedBashCompletionTask

  def test_bash_completion_loads_template(self):
    self.assert_console_output_contains("# Pants Autocompletion Support")
