# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.exceptions import TaskError
from pants.engine.engine import Engine
from pants_test.base.context_utils import create_context
from pants_test.engine.base_engine_test import EngineTestBase


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
      super(EngineTest.RecordingEngine, self).__init__()
      self._action = action
      self._attempts = []

    @property
    def attempts(self):
      return self._attempts

    def attempt(self, context, phases):
      self._attempts.append((context, phases))
      if self._action:
        self._action()

  def setUp(self):
    self.context = create_context()

  def assert_attempt(self, engine, *phase_names):
    self.assertEqual(1, len(engine.attempts))

    context, phases = engine.attempts[0]
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
