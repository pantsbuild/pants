# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.list_goals import ListGoals
from pants.backend.core.tasks.task import Task
from pants.goal.goal import Goal
from pants.goal.phase import Phase
from pants_test.tasks.test_base import ConsoleTaskTest


class ListGoalsTest(ConsoleTaskTest):
  _INSTALLED_HEADER = 'Installed goals:'
  _UNDOCUMENTED_HEADER = 'Undocumented goals:'
  _LIST_GOALS_NAME = 'goals'
  _LIST_GOALS_DESC = 'List all documented goals.'
  _LLAMA_NAME = 'llama'
  _LLAMA_DESC = 'With such handsome fiber, no wonder everyone loves Llamas.'
  _ALPACA_NAME = 'alpaca'

  @classmethod
  def task_type(cls):
    return ListGoals

  class LlamaTask(Task):
    pass

  class AlpacaTask(Task):
    pass

  def test_list_goals(self):
    Phase.clear()
    self.assert_console_output(self._INSTALLED_HEADER)

    Goal(name=self._LIST_GOALS_NAME, action=ListGoals)\
      .install().with_description(self._LIST_GOALS_DESC)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  %s: %s' % (self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
    )

    Goal(name=self._LLAMA_NAME, action=ListGoalsTest.LlamaTask)\
      .install().with_description(self._LLAMA_DESC)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  %s: %s' % (self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  %s: %s' % (self._LLAMA_NAME, self._LLAMA_DESC),
    )

    Goal(name=self._ALPACA_NAME, action=ListGoalsTest.AlpacaTask, dependencies=[self._LLAMA_NAME])\
      .install()
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  %s: %s' % (self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  %s: %s' % (self._LLAMA_NAME, self._LLAMA_DESC),
    )

  def test_list_goals_all(self):
    Phase.clear()

    Goal(name=self._LIST_GOALS_NAME, action=ListGoals)\
      .install().with_description(self._LIST_GOALS_DESC)
    Goal(name=self._LLAMA_NAME, action=ListGoalsTest.LlamaTask)\
      .install().with_description(self._LLAMA_DESC)
    Goal(name=self._ALPACA_NAME, action=ListGoalsTest.AlpacaTask, dependencies=[self._LLAMA_NAME])\
      .install()

    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  %s: %s' % (self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  %s: %s' % (self._LLAMA_NAME, self._LLAMA_DESC),
      '',
      self._UNDOCUMENTED_HEADER,
      '  %s' % self._ALPACA_NAME,
      args=['--test-all'],
    )

  def test_list_goals_graph(self):
    Phase.clear()

    Goal(name=self._LIST_GOALS_NAME, action=ListGoals)\
      .install().with_description(self._LIST_GOALS_DESC)
    Goal(name=self._LLAMA_NAME, action=ListGoalsTest.LlamaTask)\
      .install().with_description(self._LLAMA_DESC)
    Goal(name=self._ALPACA_NAME, action=ListGoalsTest.AlpacaTask, dependencies=[self._LLAMA_NAME])\
      .install()

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
      args=['--test-graph'],
    )
