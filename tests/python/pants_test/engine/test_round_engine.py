# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools

from pants.backend.core.tasks.task import Task
from pants.engine.round_engine import RoundEngine
from pants_test.base_test import BaseTest
from pants_test.engine.base_engine_test import EngineTestBase


class RoundEngineTest(EngineTestBase, BaseTest):
  def setUp(self):
    super(RoundEngineTest, self).setUp()

    self.set_options_for_scope('', explain=False)
    for outer in ['goal1', 'goal2', 'goal3', 'goal4', 'goal5']:
      for inner in ['task1', 'task2', 'task3', 'task4', 'task5']:
        self.set_options_for_scope('{}.{}'.format(outer, inner),
                                   level='info', colors=False)
    self._context = self.context()
    self.assertTrue(self._context.is_unlocked())

    self.engine = RoundEngine()
    self.actions = []

  def tearDown(self):
    self.assertTrue(self._context.is_unlocked())
    super(RoundEngineTest, self).tearDown()

  def alternate_target_roots_action(self, tag):
    return 'alternate_target_roots', tag, self._context

  def prepare_action(self, tag):
    return 'prepare', tag, self._context

  def execute_action(self, tag):
    return 'execute', tag, self._context

  def construct_action(self, tag):
    return 'construct', tag, self._context

  def record(self, tag, product_types=None, required_data=None, alternate_target_roots=None):

    class RecordingTask(Task):
      options_scope = tag

      @classmethod
      def product_types(cls):
        return product_types or []

      @classmethod
      def alternate_target_roots(cls, options, address_mapper, build_graph):
        self.actions.append(self.alternate_target_roots_action(tag))
        return alternate_target_roots

      @classmethod
      def prepare(cls, options, round_manager):
        for requirement in (required_data or ()):
          round_manager.require_data(requirement)
        self.actions.append(self.prepare_action(tag))

      def __init__(me, *args, **kwargs):
        super(RecordingTask, me).__init__(*args, **kwargs)
        self.actions.append(self.construct_action(tag))

      def execute(me):
        self.actions.append(self.execute_action(tag))

    return RecordingTask

  def install_task(self, name, product_types=None, goal=None, required_data=None,
                   alternate_target_roots=None):
    task_type = self.record(name, product_types, required_data, alternate_target_roots)
    return super(RoundEngineTest, self).install_task(name=name, action=task_type, goal=goal)

  def assert_actions(self, *expected_execute_ordering):
    expected_pre_execute_actions = set()
    expected_execute_actions = []
    for action in expected_execute_ordering:
      expected_pre_execute_actions.add(self.alternate_target_roots_action(action))
      expected_pre_execute_actions.add(self.prepare_action(action))
      expected_execute_actions.append(self.construct_action(action))
      expected_execute_actions.append(self.execute_action(action))

    expeceted_execute_actions_length = len(expected_execute_ordering) * 2
    self.assertEqual(expected_pre_execute_actions,
                     set(self.actions[:-expeceted_execute_actions_length]))
    self.assertEqual(expected_execute_actions, self.actions[-expeceted_execute_actions_length:])

  def test_lifecycle_ordering(self):
    self.install_task('task1', goal='goal1', product_types=['1'])
    self.install_task('task2', goal='goal1', product_types=['2'], required_data=['1'])
    self.install_task('task3', goal='goal3', product_types=['3'], required_data=['2'])
    self.install_task('task4', goal='goal4', required_data=['1', '2', '3'])

    self.engine.attempt(self._context, self.as_goals('goal4'))

    self.assert_actions('task1', 'task2', 'task3', 'task4')

  def test_lifecycle_ordering_install_order_invariant(self):
    # Here we swap the order of goal3 and goal4 task installation from the order in
    # `test_lifecycle_ordering` above.  We can't swap task1 and task2 since they purposefully
    # do have an implicit order dependence with a dep inside the same goal.
    self.install_task('task1', goal='goal1', product_types=['1'])
    self.install_task('task2', goal='goal1', product_types=['2'], required_data=['1'])
    self.install_task('task4', goal='goal4', required_data=['1', '2', '3'])
    self.install_task('task3', goal='goal3', product_types=['3'], required_data=['2'])

    self.engine.attempt(self._context, self.as_goals('goal4'))

    self.assert_actions('task1', 'task2', 'task3', 'task4')

  def test_inter_goal_dep(self):
    self.install_task('task1', goal='goal1', product_types=['1'])
    self.install_task('task2', goal='goal1', required_data=['1'])

    self.engine.attempt(self._context, self.as_goals('goal1'))

    self.assert_actions('task1', 'task2')

  def test_inter_goal_dep_self_cycle(self):
    self.install_task('task1', goal='goal1', product_types=['1'], required_data=['1'])

    with self.assertRaises(self.engine.TaskOrderError):
      self.engine.attempt(self._context, self.as_goals('goal1'))

  def test_inter_goal_dep_downstream(self):
    self.install_task('task1', goal='goal1', required_data=['1'])
    self.install_task('task2', goal='goal1', product_types=['1'])

    with self.assertRaises(self.engine.TaskOrderError):
      self.engine.attempt(self._context, self.as_goals('goal1'))

  def test_missing_product(self):
    self.install_task('task1', goal='goal1', required_data=['1'])

    with self.assertRaises(self.engine.MissingProductError):
      self.engine.attempt(self._context, self.as_goals('goal1'))

  def test_goal_cycle_direct(self):
    self.install_task('task1', goal='goal1', required_data=['2'], product_types=['1'])
    self.install_task('task2', goal='goal2', required_data=['1'], product_types=['2'])

    for goal in ('goal1', 'goal2'):
      with self.assertRaises(self.engine.GoalCycleError):
        self.engine.attempt(self._context, self.as_goals(goal))

  def test_goal_cycle_indirect(self):
    self.install_task('task1', goal='goal1', required_data=['2'], product_types=['1'])
    self.install_task('task2', goal='goal2', required_data=['3'], product_types=['2'])
    self.install_task('task3', goal='goal3', required_data=['1'], product_types=['3'])

    for goal in ('goal1', 'goal2', 'goal3'):
      with self.assertRaises(self.engine.GoalCycleError):
        self.engine.attempt(self._context, self.as_goals(goal))

  def test_goal_ordering_unconstrained_respects_cli_order(self):
    self.install_task('task1', goal='goal1')
    self.install_task('task2', goal='goal2')
    self.install_task('task3', goal='goal3')

    for permutation in itertools.permutations([('task1', 'goal1'),
                                               ('task2', 'goal2'),
                                               ('task3', 'goal3')]):
      self.actions = []
      self.engine.attempt(self._context, self.as_goals(*[goal for task, goal in permutation]))

      expected_execute_actions = [task for task, goal in permutation]
      self.assert_actions(*expected_execute_actions)

  def test_goal_ordering_constrained_conflicts_cli_order(self):
    self.install_task('task1', goal='goal1', required_data=['2'])
    self.install_task('task2', goal='goal2', product_types=['2'])

    self.engine.attempt(self._context, self.as_goals('goal1', 'goal2'))

    self.assert_actions('task2', 'task1')

  def test_goal_ordering_mixed_constraints_and_cli_order(self):
    self.install_task('task1', goal='goal1')
    self.install_task('task2', goal='goal2')
    self.install_task('task3', goal='goal3')
    self.install_task('task4', goal='goal4', required_data=['5'])
    self.install_task('task5', goal='goal5', product_types=['5'])

    self.engine.attempt(self._context,
                        self.as_goals('goal1', 'goal2', 'goal4', 'goal5', 'goal3'))

    self.assert_actions('task1', 'task2', 'task5', 'task4', 'task3')

  def test_cli_goals_deduped(self):
    self.install_task('task1', goal='goal1')
    self.install_task('task2', goal='goal2')
    self.install_task('task3', goal='goal3')

    self.engine.attempt(self._context,
                        self.as_goals('goal1', 'goal2', 'goal1', 'goal3', 'goal2'))

    self.assert_actions('task1', 'task2', 'task3')

  def test_replace_target_roots(self):
    self.install_task('task1', goal='goal1')
    self.install_task('task2', goal='goal2', alternate_target_roots=[42])

    self.assertEquals([], self._context.target_roots)
    self.engine.attempt(self._context, self.as_goals('goal1', 'goal2'))
    self.assertEquals([42], self._context.target_roots)

  def test_replace_target_roots_conflict(self):
    self.install_task('task1', goal='goal1', alternate_target_roots=[42])
    self.install_task('task2', goal='goal2', alternate_target_roots=[1, 2])

    with self.assertRaises(self.engine.TargetRootsReplacement.ConflictingProposalsError):
      self.engine.attempt(self._context, self.as_goals('goal1', 'goal2'))
