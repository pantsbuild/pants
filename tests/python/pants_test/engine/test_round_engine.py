# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import itertools

from pants.backend.core.tasks.task import Task
from pants.engine.round_engine import RoundEngine
from pants_test.base_test import BaseTest
from pants_test.engine.base_engine_test import EngineTestBase


class RoundEngineTest(EngineTestBase, BaseTest):
  def setUp(self):
    super(RoundEngineTest, self).setUp()

    self._context = self.context()
    self.assertTrue(self._context.is_unlocked())

    self.engine = RoundEngine()
    self.actions = []

  def tearDown(self):
    self.assertTrue(self._context.is_unlocked())
    super(RoundEngineTest, self).tearDown()

  def construct_action(self, tag):
    return 'construct', tag, self._context

  def prepare_action(self, tag):
    return 'prepare', tag, self._context

  def execute_action(self, tag):
    return 'execute', tag, self._context

  def record(self, tag, product_types=None, required_data=None):
    class RecordingTask(Task):
      def __init__(me, context, workdir):
        super(RecordingTask, me).__init__(context, workdir)
        self.actions.append(self.construct_action(tag))

      @classmethod
      def product_types(cls):
        return product_types or []

      def prepare(me, round_manager):
        for requirement in (required_data or ()):
          round_manager.require_data(requirement)
        self.actions.append(self.prepare_action(tag))

      def execute(me):
        self.actions.append(self.execute_action(tag))

    return RecordingTask

  def install_task(self, name, product_types=None, phase=None, required_data=None):
    task = self.record(name, product_types, required_data)
    return super(RoundEngineTest, self).install_task(name=name, action=task, phase=phase)

  def assert_actions(self, *expected_execute_ordering):
    expected_pre_execute_actions = set()
    expected_execute_actions = []
    for action in expected_execute_ordering:
      expected_pre_execute_actions.add(self.construct_action(action))
      expected_pre_execute_actions.add(self.prepare_action(action))
      expected_execute_actions.append(self.execute_action(action))

    self.assertEqual(expected_pre_execute_actions,
                     set(self.actions[:-len(expected_execute_ordering)]))
    self.assertEqual(expected_execute_actions, self.actions[-len(expected_execute_ordering):])

  def test_lifecycle_ordering(self):
    self.install_task('task1', phase='phase1', product_types=['1'])
    self.install_task('task2', phase='phase1', product_types=['2'], required_data=['1'])
    self.install_task('task3', phase='phase3', product_types=['3'], required_data=['2'])
    self.install_task('task4', phase='phase4', required_data=['1', '2', '3'])

    self.engine.attempt(self._context, self.as_phases('phase4'))

    self.assert_actions('task1', 'task2', 'task3', 'task4')

  def test_lifecycle_ordering_install_order_invariant(self):
    # Here we swap the order of phase3 and phase4 task installation from the order in
    # `test_lifecycle_ordering` above.  We can't swap task1 and task2 since they purposefully
    # do have an implicit order dependence with a dep inside the same phase.
    self.install_task('task1', phase='phase1', product_types=['1'])
    self.install_task('task2', phase='phase1', product_types=['2'], required_data=['1'])
    self.install_task('task4', phase='phase4', required_data=['1', '2', '3'])
    self.install_task('task3', phase='phase3', product_types=['3'], required_data=['2'])

    self.engine.attempt(self._context, self.as_phases('phase4'))

    self.assert_actions('task1', 'task2', 'task3', 'task4')

  def test_inter_phase_dep(self):
    self.install_task('task1', phase='phase1', product_types=['1'])
    self.install_task('task2', phase='phase1', required_data=['1'])

    self.engine.attempt(self._context, self.as_phases('phase1'))

    self.assert_actions('task1', 'task2')

  def test_inter_phase_dep_self_cycle(self):
    self.install_task('task1', phase='phase1', product_types=['1'], required_data=['1'])

    with self.assertRaises(self.engine.TaskOrderError):
      self.engine.attempt(self._context, self.as_phases('phase1'))

  def test_inter_phase_dep_downstream(self):
    self.install_task('task1', phase='phase1', required_data=['1'])
    self.install_task('task2', phase='phase1', product_types=['1'])

    with self.assertRaises(self.engine.TaskOrderError):
      self.engine.attempt(self._context, self.as_phases('phase1'))

  def test_missing_product(self):
    self.install_task('task1', phase='phase1', required_data=['1'])

    with self.assertRaises(self.engine.MissingProductError):
      self.engine.attempt(self._context, self.as_phases('phase1'))

  def test_phase_cycle_direct(self):
    self.install_task('task1', phase='phase1', required_data=['2'], product_types=['1'])
    self.install_task('task2', phase='phase2', required_data=['1'], product_types=['2'])

    for phase in ('phase1', 'phase2'):
      with self.assertRaises(self.engine.PhaseCycleError):
        self.engine.attempt(self._context, self.as_phases(phase))

  def test_phase_cycle_indirect(self):
    self.install_task('task1', phase='phase1', required_data=['2'], product_types=['1'])
    self.install_task('task2', phase='phase2', required_data=['3'], product_types=['2'])
    self.install_task('task3', phase='phase3', required_data=['1'], product_types=['3'])

    for phase in ('phase1', 'phase2', 'phase3'):
      with self.assertRaises(self.engine.PhaseCycleError):
        self.engine.attempt(self._context, self.as_phases(phase))

  def test_phase_ordering_unconstrained_respects_cli_order(self):
    self.install_task('task1', phase='phase1')
    self.install_task('task2', phase='phase2')
    self.install_task('task3', phase='phase3')

    for permutation in itertools.permutations([('task1', 'phase1'),
                                               ('task2', 'phase2'),
                                               ('task3', 'phase3')]):
      self.actions = []
      self.engine.attempt(self._context, self.as_phases(*[phase for task, phase in permutation]))

      expected_execute_actions = [task for task, phase in permutation]
      self.assert_actions(*expected_execute_actions)

  def test_phase_ordering_constrained_conflicts_cli_order(self):
    self.install_task('task1', phase='phase1', required_data=['2'])
    self.install_task('task2', phase='phase2', product_types=['2'])

    self.engine.attempt(self._context, self.as_phases('phase1', 'phase2'))

    self.assert_actions('task2', 'task1')

  def test_phase_ordering_mixed_constraints_and_cli_order(self):
    self.install_task('task1', phase='phase1')
    self.install_task('task2', phase='phase2')
    self.install_task('task3', phase='phase3')
    self.install_task('task4', phase='phase4', required_data=['5'])
    self.install_task('task5', phase='phase5', product_types=['5'])

    self.engine.attempt(self._context,
                        self.as_phases('phase1', 'phase2', 'phase4', 'phase5', 'phase3'))

    self.assert_actions('task1', 'task2', 'task5', 'task4', 'task3')

  def test_cli_phases_deduped(self):
    self.install_task('task1', phase='phase1')
    self.install_task('task2', phase='phase2')
    self.install_task('task3', phase='phase3')

    self.engine.attempt(self._context,
                        self.as_phases('phase1', 'phase2', 'phase1', 'phase3', 'phase2'))

    self.assert_actions('task1', 'task2', 'task3')


