# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import mox

from pants.engine..base.context_utils import create_context
from pants.engine.base_engine_test import EngineTestBase
from pants.engine.engine import Engine, Timer
from pants.tasks import TaskError


class TimerTest(mox.MoxTestBase, EngineTestBase):
  def setUp(self):
    super(TimerTest, self).setUp()
    self.ticker = self.mox.CreateMockAnything()

  def test_begin(self):
    self.ticker().AndReturn(0)  # start timer
    self.ticker().AndReturn(11)  # start timed goal_succeed #1
    self.ticker().AndReturn(13)  # finish timed goal_succeed #1
    self.ticker().AndReturn(17)  # start timed goal_succeed #2
    self.ticker().AndReturn(23)  # finish timed goal_succeed #2
    self.ticker().AndReturn(29)  # start timed goal_fail #1
    self.ticker().AndReturn(42)  # finish timed goal_fail #1
    self.ticker().AndReturn(42)  # start timed goal_muddle #1
    self.ticker().AndReturn(42)  # finish timed goal_muddle #1
    self.ticker().AndReturn(42)  # finish timer
    self.mox.ReplayAll()

    goal_succeed = self.installed_goal('succeed', phase='first')
    goal_fail = self.installed_goal('fail', phase='first')
    goal_muddle = self.installed_goal('muddle', phase='second')

    with Timer.begin(self.ticker) as timer:
      with timer.timed(goal_succeed):
        pass
      with timer.timed(goal_succeed):
        pass
      with timer.timed(goal_fail):
        pass
      with timer.timed(goal_muddle):
        pass

    self.assertEqual(42, timer.elapsed)

    first_timings = timer.timings.pop(self.as_phase('first'))
    second_timings = timer.timings.pop(self.as_phase('second'))
    self.assertEqual(0, len(timer.timings))

    goal_succeed_timings = first_timings.pop(goal_succeed)
    goal_fail_timings = first_timings.pop(goal_fail)
    self.assertEqual(0, len(first_timings))
    self.assertEqual([2, 6], goal_succeed_timings)
    self.assertEqual([13], goal_fail_timings)

    goal_muddle_timings = second_timings.pop(goal_muddle)
    self.assertEqual(0, len(second_timings))
    self.assertEqual([0], goal_muddle_timings)


class ExecutionOrderTest(EngineTestBase):
  def test_execution_order(self):
    self.installed_goal('invalidate')
    self.installed_goal('clean-all', dependencies=['invalidate'])

    self.installed_goal('resolve')
    self.installed_goal('javac', dependencies=['resolve'], phase='compile')
    self.installed_goal('scalac', dependencies=['resolve'], phase='compile')
    self.installed_goal('junit', dependencies=['compile'], phase='test')

    self.assertEqual(self.as_phases('invalidate', 'clean-all', 'resolve', 'compile', 'test'),
                     list(Engine.execution_order(self.as_phases('clean-all', 'test'))))

    self.assertEqual(self.as_phases('resolve', 'compile', 'test', 'invalidate', 'clean-all'),
                     list(Engine.execution_order(self.as_phases('test', 'clean-all'))))


class EngineTest(EngineTestBase):
  class RecordingEngine(Engine):
    def __init__(self, action=None):
      super(EngineTest.RecordingEngine, self).__init__(print_timing=False)
      self._action = action
      self._attempts = []

    @property
    def attempts(self):
      return self._attempts

    def attempt(self, timer, context, phases):
      self._attempts.append((timer, context, phases))
      if self._action:
        self._action()

  def setUp(self):
    self.context = create_context()

  def assert_attempt(self, engine, *phase_names):
    self.assertEqual(1, len(engine.attempts))

    timer, context, phases = engine.attempts[0]
    self.assertTrue(timer.elapsed >= 0, 'Expected timer to be finished.')
    self.assertEqual(self.context, context)
    self.assertEqual(self.as_phases(*phase_names), phases)

  def test_execute_success(self):
    engine = self.RecordingEngine()
    result = engine.execute(self.context, self.as_phases('one', 'two'))
    self.assertEqual(0, result)
    self.assert_attempt(engine, 'one', 'two')

  def _throw(self, error):
    def throw():
      raise error
    return throw

  def test_execute_raise(self):
    engine = self.RecordingEngine(action=self._throw(TaskError()))
    result = engine.execute(self.context, self.as_phases('three'))
    self.assertEqual(1, result)
    self.assert_attempt(engine, 'three')

  def test_execute_code(self):
    engine = self.RecordingEngine(action=self._throw(TaskError(exit_code=42)))
    result = engine.execute(self.context, self.as_phases('four', 'five', 'six'))
    self.assertEqual(42, result)
    self.assert_attempt(engine, 'four', 'five', 'six')
