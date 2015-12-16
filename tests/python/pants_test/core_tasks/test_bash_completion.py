# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.core_tasks.bash_completion import BashCompletion
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class MockedBashCompletion(BashCompletion):
  """A version of the BashCompletion, with the help introspection mocked out."""

  def get_autocomplete_options_by_scope(self):
    return {'': []}


class BashCompletionTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return MockedBashCompletion

  def test_bash_completion_loads_template(self):
    self.assert_console_output_contains("# Pants Autocompletion Support")
