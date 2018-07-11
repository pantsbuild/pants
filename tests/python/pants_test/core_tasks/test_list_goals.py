# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from unittest import expectedFailure

from pants.core_tasks.list_goals import ListGoals
from pants.goal.error import GoalError
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar
from pants.task.task import Task
from pants_test.task_test_base import ConsoleTaskTestBase


class ListGoalsTest(ConsoleTaskTestBase):
  class NoopTask(Task):
    def execute(self):
      pass

  _INSTALLED_HEADER = 'Installed goals:'
  _UNDOCUMENTED_HEADER = 'Undocumented goals:'
  _LIST_GOALS_NAME = 'goals'
  _LIST_GOALS_DESC = 'List available goals.'
  _LIST_GOALS_TASK = TaskRegistrar('list-goals', NoopTask)
  _LLAMA_NAME = 'llama'
  _LLAMA_DESC = 'With such handsome fiber, no wonder everyone loves Llamas.'
  _LLAMA_TASK = TaskRegistrar('winamp', NoopTask)
  _ALPACA_NAME = 'alpaca'
  _ALPACA_TASK = TaskRegistrar('alpaca', NoopTask)

  @classmethod
  def task_type(cls):
    return ListGoals

  def test_list_goals(self):
    Goal.clear()
    self.assert_console_output(self._INSTALLED_HEADER)

    # Goals with no tasks should always be elided.
    list_goals_goal = Goal.register(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC)
    self.assert_console_output(self._INSTALLED_HEADER)

    list_goals_goal.install(self._LIST_GOALS_TASK)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  {0}: {1}'.format(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
    )

    Goal.register(self._LLAMA_NAME, self._LLAMA_DESC).install(self._LLAMA_TASK)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  {0}: {1}'.format(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  {0}: {1}'.format(self._LLAMA_NAME, self._LLAMA_DESC),
    )

    Goal.register(self._ALPACA_NAME, description='').install(self._ALPACA_TASK)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  {0}: {1}'.format(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  {0}: {1}'.format(self._LLAMA_NAME, self._LLAMA_DESC),
    )

  def test_list_goals_all(self):
    Goal.clear()

    Goal.register(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC).install(self._LIST_GOALS_TASK)

    # Goals with no tasks should always be elided.
    Goal.register(self._LLAMA_NAME, self._LLAMA_DESC)

    Goal.register(self._ALPACA_NAME, description='').install(self._ALPACA_TASK)

    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  {0}: {1}'.format(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '',
      self._UNDOCUMENTED_HEADER,
      '  {0}'.format(self._ALPACA_NAME),
      options={'all': True}
    )

  def test_register_duplicate_task_name_is_error(self):
    Goal.clear()

    class NoopTask(Task):
      def execute(self):
        pass

    class OtherNoopTask(Task):
      def execute(self):
        pass

    goal = Goal.register(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC)
    task_name = 'foo'
    goal.install(TaskRegistrar(task_name, NoopTask))

    with self.assertRaises(GoalError) as ctx:
      goal.install(TaskRegistrar(task_name, OtherNoopTask))

    self.assertIn('foo', ctx.exception.message)
    self.assertIn(self._LIST_GOALS_NAME, ctx.exception.message)

  def test_register_duplicate_task_name_is_not_error_when_replacing(self):
    Goal.clear()

    class NoopTask(Task):
      def execute(self):
        pass

    class OtherNoopTask(Task):
      def execute(self):
        pass

    goal = Goal.register(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC)
    task_name = 'foo'
    goal.install(TaskRegistrar(task_name, NoopTask))
    goal.install(TaskRegistrar(task_name, OtherNoopTask), replace=True)

    self.assertTrue(issubclass(goal.task_type_by_name(task_name), OtherNoopTask))

  # TODO(John Sirois): Re-enable when fixing up ListGoals `--graph` in
  # https://github.com/pantsbuild/pants/issues/918
  @expectedFailure
  def test_list_goals_graph(self):
    Goal.clear()

    Goal.register(self._LIST_GOALS_NAME, self._LIST_GOALS_DESC).install(self._LIST_GOALS_TASK)
    Goal.register(self._LLAMA_NAME, self._LLAMA_DESC).install(self._LLAMA_TASK)
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
