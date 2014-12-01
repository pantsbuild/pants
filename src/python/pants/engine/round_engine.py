# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple
import os

from twitter.common.collections.orderedset import OrderedSet
from twitter.common.collections.ordereddict import OrderedDict

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.engine.engine import Engine
from pants.engine.round_manager import RoundManager


class GoalExecutor(object):
  def __init__(self, context, goal, tasks_by_name):
    self._context = context
    self._goal = goal
    self._tasks_by_name = tasks_by_name

  @property
  def goal(self):
    return self._goal

  def attempt(self, explain):
    """Attempts to execute the goal's tasks in installed order.

    :param bool explain: If ``True`` then the goal plan will be explained instead of being
                         executed.
    """
    with self._context.new_workunit(name=self._goal.name, labels=[WorkUnit.GOAL]):
      for name, task in reversed(self._tasks_by_name.items()):
        with self._context.new_workunit(name=name, labels=[WorkUnit.TASK]):
          if explain:
            self._context.log.debug('Skipping execution of %s in explain mode' % name)
          else:
            task.execute()

      if explain:
        reversed_tasks_by_name = reversed(self._tasks_by_name.items())
        goal_to_task = ', '.join(
            '%s->%s' % (name, task.__class__.__name__) for name, task in reversed_tasks_by_name)
        print('{goal} [{goal_to_task}]'.format(goal=self._goal.name, goal_to_task=goal_to_task))


class RoundEngine(Engine):

  class DependencyError(ValueError):
    """Indicates a Task has an unsatisfiable data dependency."""

  class GoalCycleError(DependencyError):
    """Indicates there is a cycle in the goal dependency graph."""

  class TaskOrderError(DependencyError):
    """Indicates a task depends on data produced by another task in the same goal that is
    scheduled to runs after it.
    """

  class MissingProductError(DependencyError):
    """Indicates an expressed data dependency if not provided by any installed task."""

  GoalInfo = namedtuple('GoalInfo', ['goal', 'tasks_by_name', 'goal_dependencies'])

  def _topological_sort(self, goal_info_by_goal):
    dependees_by_goal = OrderedDict()

    def add_dependee(goal, dependee=None):
      dependees = dependees_by_goal.get(goal)
      if dependees is None:
        dependees = set()
        dependees_by_goal[goal] = dependees
      if dependee:
        dependees.add(dependee)

    for goal, goal_info in goal_info_by_goal.items():
      add_dependee(goal)
      for dependency in goal_info.goal_dependencies:
        add_dependee(dependency, goal)

    satisfied = set()
    while dependees_by_goal:
      count = len(dependees_by_goal)
      for goal, dependees in dependees_by_goal.items():
        unsatisfied = len(dependees - satisfied)
        if unsatisfied == 0:
          satisfied.add(goal)
          dependees_by_goal.pop(goal)
          yield goal_info_by_goal[goal]
          break
      if len(dependees_by_goal) == count:
        for dependees in dependees_by_goal.values():
          dependees.difference_update(satisfied)
        # TODO(John Sirois): Do a better job here and actually collect and print cycle paths
        # between Goals/Tasks.  The developer can most directly address that data.
        raise self.GoalCycleError('Cycle detected in goal dependencies:\n\t{0}'
                                   .format('\n\t'.join('{0} <- {1}'.format(goal, list(dependees))
                                                       for goal, dependees
                                                       in dependees_by_goal.items())))

  def _visit_goal(self, goal, context, goal_info_by_goal):
    if goal in goal_info_by_goal:
      return

    tasks_by_name = OrderedDict()
    goal_dependencies = set()
    visited_task_types = set()
    for task_name in reversed(goal.ordered_task_names()):
      task_type = goal.task_type_by_name(task_name)
      visited_task_types.add(task_type)

      task_workdir = os.path.join(context.new_options.for_global_scope().pants_workdir,
                                  goal.name, task_name)
      task = task_type(context, task_workdir)
      tasks_by_name[task_name] = task

      round_manager = RoundManager(context)
      task.prepare(round_manager)
      try:
        dependencies = round_manager.get_dependencies()
        for producer_info in dependencies:
          producer_goal = producer_info.goal
          if producer_goal == goal:
            if producer_info.task_type in visited_task_types:
              ordering = '\n\t'.join("[{0}] '{1}' {2}".format(i, tn,
                                                              goal.task_type_by_name(tn).__name__)
                                     for i, tn in enumerate(goal.ordered_task_names()))
              raise self.TaskOrderError(
                  "TaskRegistrar '{name}' with action {consumer_task} depends on {data} from task "
                  "{producer_task} which is ordered after it in the '{goal}' goal:\n\t{ordering}"
                  .format(name=task_name,
                          consumer_task=task_type.__name__,
                          data=producer_info.product_type,
                          producer_task=producer_info.task_type.__name__,
                          goal=goal.name,
                          ordering=ordering))
            else:
              # We don't express dependencies on downstream tasks in this same goal.
              pass
          else:
            goal_dependencies.add(producer_goal)
      except round_manager.MissingProductError as e:
        raise self.MissingProductError(
            "Could not satisfy data dependencies for goal '{name}' with action {action}: {error}"
            .format(name=task_name, action=task_type.__name__, error=e))

    goal_info = self.GoalInfo(goal, tasks_by_name, goal_dependencies)
    goal_info_by_goal[goal] = goal_info

    for goal_dependency in goal_dependencies:
      self._visit_goal(goal_dependency, context, goal_info_by_goal)

  def _prepare(self, context, goals):
    if len(goals) == 0:
      raise TaskError('No goals to prepare')

    goal_info_by_goal = OrderedDict()
    for goal in reversed(OrderedSet(goals)):
      self._visit_goal(goal, context, goal_info_by_goal)

    for goal_info in reversed(list(self._topological_sort(goal_info_by_goal))):
      yield GoalExecutor(context, goal_info.goal, goal_info.tasks_by_name)

  def attempt(self, context, goals):
    goal_executors = list(self._prepare(context, goals))
    execution_goals = ' -> '.join(e.goal.name for e in goal_executors)
    context.log.info('Executing tasks in goals: {goals}'.format(goals=execution_goals))

    explain = context.new_options.for_global_scope().explain
    if explain:
      print('Goal Execution Order:\n\n%s\n' % execution_goals)
      print('Goal [TaskRegistrar->Task] Order:\n')

    serialized_goals_executors = [ge for ge in goal_executors if ge.goal.serialize]
    outer_lock_holder = serialized_goals_executors[-1] if serialized_goals_executors else None

    if outer_lock_holder:
      context.acquire_lock()
    try:
      for goal_executor in goal_executors:
        goal_executor.attempt(explain)
        if goal_executor is outer_lock_holder:
          context.release_lock()
          outer_lock_holder = None
    finally:
      if outer_lock_holder:
        context.release_lock()
