# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.engine.engine import Engine


class LinearEngine(Engine):
  """An engine that operates on a linearized phase graph.

  In order to attempt to execute a set of requested phases against a portion of the target graph
  the engine 1st linearizes the phase graph such that tasks that depend on a phase are ordered
  after all tasks in that phase.  The linearization further maintains strict in-phase ordering of
  tasks as-installed in their phases.

  With this linearized task list the engine 1st prepares all the tasks in reverse order such that
  a task depending on products from an earlier phase can request these.

  Finally the engine executes the prepared tasks in the order established in the linearized task
  list.
  """

  class PhaseExecutor(object):
    def __init__(self, context, phase, tasks_by_goal):
      self._context = context
      self._phase = phase
      self._tasks_by_goal = tasks_by_goal

    @property
    def phase(self):
      return self._phase

    def attempt(self, explain):
      """Attempts to execute the phase's tasks in installed order.

      :param bool explain: If ``True`` then the phase plan will be explained instead of being
        executed.
      """
      goals = self._phase.goals()
      if not goals:
        raise TaskError('No goals installed for phase %s' % self._phase)

      with self._context.new_workunit(name=self._phase.name, labels=[WorkUnit.PHASE]):
        for goal in goals:
          with self._context.new_workunit(name=goal.name, labels=[WorkUnit.GOAL]):
            if explain:
              self._context.log.debug("Skipping execution of %s in explain mode" % goal.name)
            else:
              task = self._tasks_by_goal[goal]
              task.execute()

        if explain:
          tasks_by_goalname = dict((goal.name, task.__class__.__name__)
                                   for goal, task in self._tasks_by_goal.items())

          def expand_goal(goal):
            task_name = tasks_by_goalname[goal.name]
            return "%s->%s" % (goal.name, task_name)

          goal_to_task = ", ".join(expand_goal(goal) for goal in goals)
          print("%s [%s]" % (self._phase, goal_to_task))

  @classmethod
  def _prepare(cls, context, phases):
    tasks_by_goal = {}

    # We loop here because a prepared goal may introduce new BUILDs and thereby new Goals/Phases.
    # We need to prepare these in a subsequent loop until the set of phases and goals quiesces.
    prepared_goals = set()
    round_num = 0
    while True:
      phases = list(cls.execution_order(phases))
      if prepared_goals == reduce(lambda goals, p: goals | set(p.goals()), phases, set()):
        break

      round_num += 1
      context.log.debug('Preparing goals in round %d' % round_num)
      # Prepare tasks roots to leaves and allow for downstream tasks requiring products from
      # upstream tasks they depend upon.
      pants_workdir = context.config.getdefault('pants_workdir')
      for phase in reversed(phases):
        for goal in reversed(phase.goals()):
          if goal not in prepared_goals:
            context.log.debug('preparing: %s:%s' % (phase.name, goal.name))
            prepared_goals.add(goal)
            task_workdir = os.path.join(pants_workdir, phase.name, goal.name)
            # TODO(John Sirois): At some point construct the tasks in random order and only
            # prepare here to help enforce the new prepare lifecycle method.
            task = goal.task_type(context, task_workdir)
            task.prepare()
            tasks_by_goal[goal] = task

    return [cls.PhaseExecutor(context, p, tasks_by_goal) for p in phases]

  def attempt(self, context, phases):
    phase_executors = self._prepare(context, phases)

    execution_phases = ' -> '.join(e.phase.name for e in phase_executors)
    context.log.debug('Executing goals in phases %s' % execution_phases)

    explain = getattr(context.options, 'explain', False)
    if explain:
      print("Phase Execution Order:\n\n%s\n" % execution_phases)
      print("Phase [Goal->Task] Order:\n")

    # We take a conservative locking strategy and lock in the widest needed scope.  If we have a
    # linearized set of phases as such (where x -> y means x depends on y and *z means z needs to be
    # serialized):
    #   a -> b -> *c -> d -> *e -> f
    # Then we grab the lock at the beginning of f's execution and don't relinquish until the largest
    # scope serialization requirement from c is past.
    serialized_phase_executors = [pe for pe in phase_executors if pe.phase.serialize]
    if context.options.no_lock:
      outer_lock_holder = None
    else:
      outer_lock_holder = serialized_phase_executors[-1] if serialized_phase_executors else None

    if outer_lock_holder:
      context.acquire_lock()
    try:
      for phase_executor in phase_executors:
        phase_executor.attempt(explain)
        if phase_executor is outer_lock_holder:
          context.release_lock()
    finally:
      # we may fail before we reach the outer lock holder - so make sure to clean up no matter what.
      if outer_lock_holder:
        context.release_lock()
