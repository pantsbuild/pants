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

  def test_bash_completion_task(self):
    self.assert_console_output_contains("# Pants Autocompletion Support")
