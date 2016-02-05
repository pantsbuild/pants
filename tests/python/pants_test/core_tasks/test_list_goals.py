# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from unittest import expectedFailure

from pants.core_tasks.list_goals import ListGoals
from pants.goal.goal import Goal
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class ListGoalsTest(ConsoleTaskTestBase):
  _INSTALLED_HEADER = 'Installed goals:'
  _UNDOCUMENTED_HEADER = 'Undocumented goals:'
  _LIST_GOALS_NAME = 'goals'
  _LIST_GOALS_DESC = 'List available goals.'
  _LLAMA_NAME = 'llama'
  _LLAMA_DESC = 'With such handsome fiber, no wonder everyone loves Llamas.'
  _ALPACA_NAME = 'alpaca'

  @classmethod
  def task_type(cls):
    return ListGoals

  def test_list_goals(self):
    Goal.clear()
    self.assert_console_output(self._INSTALLED_HEADER)

    Goal.register(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  {0}: {1}'.format(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
    )

    Goal.register(self._LLAMA_NAME, self._LLAMA_DESC)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  {0}: {1}'.format(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  {0}: {1}'.format(self._LLAMA_NAME, self._LLAMA_DESC),
    )

    Goal.register(self._ALPACA_NAME, description='')
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  {0}: {1}'.format(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  {0}: {1}'.format(self._LLAMA_NAME, self._LLAMA_DESC),
    )

  def test_list_goals_all(self):
    Goal.clear()

    Goal.register(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC)
    Goal.register(self._LLAMA_NAME, self._LLAMA_DESC)
    Goal.register(self._ALPACA_NAME, description='')

    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  {0}: {1}'.format(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  {0}: {1}'.format(self._LLAMA_NAME, self._LLAMA_DESC),
      '',
      self._UNDOCUMENTED_HEADER,
      '  {0}'.format(self._ALPACA_NAME),
      options={'all': True}
    )

  # TODO(John Sirois): Re-enable when fixing up ListGoals `--graph` in
  # https://github.com/pantsbuild/pants/issues/918
  @expectedFailure
  def test_list_goals_graph(self):
    Goal.clear()


    Goal.register(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC)
    Goal.register(self._LLAMA_NAME, self._LLAMA_DESC)
    Goal.register(self._ALPACA_NAME, description='')

    self.assert_console_output(
      'digraph G {\n  rankdir=LR;\n  graph [compound=true];',
      '  subgraph cluster_goals {\n    node [style=filled];\n    color = blue;\n    label = "goals";',
      '    goals_goals [label="goals"];',
      '  }',
      '  subgraph cluster_llama {\n    node [style=filled];\n    color = blue;\n    label = "llama";',
      '    llama_llama [label="llama"];',
      '  }',
      '  subgraph cluster_alpaca {\n    node [style=filled];\n    color = blue;\n    label = "alpaca";',
      '    alpaca_alpaca [label="alpaca"];',
      '  }',
      '  alpaca_alpaca -> llama_llama [ltail=cluster_alpaca lhead=cluster_llama];',
      '}',
      options={'graph': True}
    )
