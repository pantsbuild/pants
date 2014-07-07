# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple
import os

from twitter.common.collections.ordereddict import OrderedDict

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.engine.engine import Engine
from pants.engine.round_manager import RoundManager


class PhaseExecutor(object):
  def __init__(self, context, phase, tasks_by_name):
    self._context = context
    self._phase = phase
    self._tasks_by_name = tasks_by_name

  @property
  def phase(self):
    return self._phase

  def attempt(self, explain):
    """Attempts to execute the phase's tasks in installed order.

    :param bool explain: If ``True`` then the phase plan will be explained instead of being
      executed.
    """
    with self._context.new_workunit(name=self._phase.name, labels=[WorkUnit.PHASE]):
      for name, task in reversed(self._tasks_by_name.items()):
        with self._context.new_workunit(name=name, labels=[WorkUnit.GOAL]):
          if explain:
            self._context.log.debug('Skipping execution of %s in explain mode' % name)
          else:
            task.execute()

      if explain:
        reversed_tasks_by_name = reversed(self._tasks_by_name.items())
        goal_to_task = ', '.join(
            '%s->%s' % (name, task.__class__.__name__) for name, task in reversed_tasks_by_name)
        print('{phase} [{goal_to_task}]'.format(phase=self._phase.name, goal_to_task=goal_to_task))


class RoundEngine(Engine):
  PhaseInfo = namedtuple('PhaseInfo', ['phase', 'tasks_by_name', 'phase_dependencies'])

  def _topological_sort(self, phase_info_by_phase):
    dependees_by_phase = OrderedDict()

    def add_dependee(phase, dependee=None):
      dependees = dependees_by_phase.get(phase)
      if dependees is None:
        dependees = set()
        dependees_by_phase[phase] = dependees
      # TODO(ity): Fix this check, this should never be called with the phase == dependee
      if dependee and dependee is not phase:
        dependees.add(dependee)

    for phase, phase_info in phase_info_by_phase.items():
      add_dependee(phase)
      for dependency in phase_info.phase_dependencies:
        add_dependee(dependency, phase)

    satisfied = set()
    while dependees_by_phase:
      count = len(dependees_by_phase)
      for phase, dependees in dependees_by_phase.items():
        unsatisfied = len(dependees - satisfied)
        if unsatisfied == 0:
          satisfied.add(phase)
          dependees_by_phase.pop(phase)
          yield phase_info_by_phase[phase]
          break
      if len(dependees_by_phase) == count:
        for dependees in dependees_by_phase.values():
          dependees.difference_update(satisfied)
        # TODO(John Sirois): Do a better job here and actually collect and print cycle paths
        # between Goals/Tasks.  The developer can most directly address that data.
        raise ValueError('Cycle detected in phase dependencies:\n\t{0}'
                         .format('\n\t'.join('{0} <- {1}'.format(phase, list(dependees))
                                             for phase, dependees in dependees_by_phase.items())))

  def _visit_phase(self, phase, context, phase_info_by_phase):
    if phase in phase_info_by_phase:
      return

    tasks_by_name = OrderedDict()

    round_manager = RoundManager(context)
    for goal in reversed(phase.goals()):
      task_workdir = os.path.join(context.config.getdefault('pants_workdir'),
                                  phase.name,
                                  goal.name)
      task = goal.task_type(context, task_workdir)
      task.prepare(round_manager)
      tasks_by_name[goal.name] = task

    products = round_manager.get_schedule()
    phase_dependencies = round_manager.lookup_phases_for_products(products)
    phase_info = self.PhaseInfo(phase, tasks_by_name, phase_dependencies)
    phase_info_by_phase[phase] = phase_info

    for phase_dependency in phase_dependencies:
      self._visit_phase(phase_dependency, context, phase_info_by_phase)

  def _prepare(self, context, phases):
    if len(phases) == 0:
      raise TaskError('No phases to prepare')

    phase_info_by_phase = OrderedDict()
    for phase in reversed(phases):
      self._visit_phase(phase, context, phase_info_by_phase)

    for phase_info in reversed(list(self._topological_sort(phase_info_by_phase))):
      yield PhaseExecutor(context, phase_info.phase, phase_info.tasks_by_name)

  def attempt(self, context, phases):
    phase_executors = list(self._prepare(context, phases))
    execution_phases = ' -> '.join(e.phase.name for e in phase_executors)
    context.log.info('Executing goals in phases: {phases}'.format(phases=execution_phases))

    explain = getattr(context.options, 'explain', False)
    if explain:
      print('Phase Execution Order:\n\n%s\n' % execution_phases)
      print('Phase [Goal->Task] Order:\n')

    serialized_phase_executors = [pe for pe in phase_executors if pe.phase.serialize]
    outer_lock_holder = serialized_phase_executors[-1] if serialized_phase_executors else None

    if outer_lock_holder:
      context.acquire_lock()
    try:
      for phase_executor in phase_executors:
        phase_executor.attempt(explain)
        if phase_executor is outer_lock_holder:
          context.release_lock()
          outer_lock_holder = None
    finally:
     if outer_lock_holder:
       context.release_lock()
