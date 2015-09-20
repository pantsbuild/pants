# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import OrderedDict, namedtuple

from twitter.common.collections.orderedset import OrderedSet

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.engine.engine import Engine
from pants.engine.round_manager import RoundManager


class GoalExecutor(object):

  def __init__(self, context, goal, tasktypes_by_name):
    self._context = context
    self._goal = goal
    self._tasktypes_by_name = tasktypes_by_name

  @property
  def goal(self):
    return self._goal

  def attempt(self, explain):
    """Attempts to execute the goal's tasks in installed order.

    :param bool explain: If ``True`` then the goal plan will be explained instead of being
                         executed.
    """
    goal_workdir = os.path.join(self._context.options.for_global_scope().pants_workdir,
                                self._goal.name)
    with self._context.new_workunit(name=self._goal.name, labels=[WorkUnitLabel.GOAL]):
      for name, task_type in reversed(self._tasktypes_by_name.items()):
        task_workdir = os.path.join(goal_workdir, name)
        task = task_type(self._context, task_workdir)
        log_config = WorkUnit.LogConfig(level=task.get_options().level, colors=task.get_options().colors)
        with self._context.new_workunit(name=name, labels=[WorkUnitLabel.TASK], log_config=log_config):
          if explain:
            self._context.log.debug('Skipping execution of {} in explain mode'.format(name))
          else:
            task.execute()

      if explain:
        reversed_tasktypes_by_name = reversed(self._tasktypes_by_name.items())
        goal_to_task = ', '.join(
            '{}->{}'.format(name, task_type.__name__) for name, task_type in reversed_tasktypes_by_name)
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

  GoalInfo = namedtuple('GoalInfo', ['goal', 'tasktypes_by_name', 'goal_dependencies'])

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

  class TargetRootsReplacement(object):

    class ConflictingProposalsError(Exception):
      """Indicates conflicting proposals for a target root replacement in a single pants run."""

    def __init__(self):
      self._proposer = None
      self._target_roots = None

    def propose_alternates(self, proposer, target_roots):
      if target_roots:
        if self._target_roots and (self._target_roots != target_roots):
          raise self.ConflictingProposalsError(
              'Already have a proposal by {0} for {1} and cannot accept conflicting proposal '
              'by {2} for {3}.'.format(self._proposer, self._target_roots, proposer, target_roots))
        self._proposer = proposer
        self._target_roots = target_roots

    def apply(self, context):
      if self._target_roots:
        context._replace_targets(self._target_roots)

  def _visit_goal(self, goal, context, goal_info_by_goal, target_roots_replacement):
    if goal in goal_info_by_goal:
      return

    tasktypes_by_name = OrderedDict()
    goal_dependencies = set()
    visited_task_types = set()
    for task_name in reversed(goal.ordered_task_names()):
      task_type = goal.task_type_by_name(task_name)
      tasktypes_by_name[task_name] = task_type
      visited_task_types.add(task_type)

      alternate_target_roots = task_type._alternate_target_roots(context.options,
                                                                 context.address_mapper,
                                                                 context.build_graph)
      target_roots_replacement.propose_alternates(task_type, alternate_target_roots)

      round_manager = RoundManager(context)
      task_type._prepare(context.options, round_manager)
      try:
        dependencies = round_manager.get_dependencies()
        for producer_info in dependencies:
          producer_goal = producer_info.goal
          if producer_goal == goal:
            if producer_info.task_type == task_type:
              # We allow a task to produce products it itself needs.  We trust the Task writer
              # to arrange for proper sequencing.
              pass
            elif producer_info.task_type in visited_task_types:
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

    goal_info = self.GoalInfo(goal, tasktypes_by_name, goal_dependencies)
    goal_info_by_goal[goal] = goal_info

    for goal_dependency in goal_dependencies:
      self._visit_goal(goal_dependency, context, goal_info_by_goal, target_roots_replacement)

  def _prepare(self, context, goals):
    if len(goals) == 0:
      raise TaskError('No goals to prepare')

    goal_info_by_goal = OrderedDict()
    target_roots_replacement = self.TargetRootsReplacement()
    for goal in reversed(OrderedSet(goals)):
      self._visit_goal(goal, context, goal_info_by_goal, target_roots_replacement)
    target_roots_replacement.apply(context)

    for goal_info in reversed(list(self._topological_sort(goal_info_by_goal))):
      yield GoalExecutor(context, goal_info.goal, goal_info.tasktypes_by_name)

  def attempt(self, context, goals):
    goal_executors = list(self._prepare(context, goals))
    execution_goals = ' -> '.join(e.goal.name for e in goal_executors)
    context.log.info('Executing tasks in goals: {goals}'.format(goals=execution_goals))

    explain = context.options.for_global_scope().explain
    if explain:
      print('Goal Execution Order:\n\n{}\n'.format(execution_goals))
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
