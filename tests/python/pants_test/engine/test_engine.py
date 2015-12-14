# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TaskError
from pants.engine.engine import Engine
from pants_test.engine.base_engine_test import EngineTestBase


class EngineTest(EngineTestBase):
  class RecordingEngine(Engine):
    def __init__(self, action=None):
      super(EngineTest.RecordingEngine, self).__init__()
      self._action = action
      self._attempts = []

    @property
    def attempts(self):
      return self._attempts

    def attempt(self, context, goals):
      self._attempts.append((context, goals))
      if self._action:
        self._action()

  def setUp(self):
    super(EngineTest, self).setUp()
    self._context = self.context()

  def assert_attempt(self, engine, *goal_names):
    self.assertEqual(1, len(engine.attempts))

    context, goals = engine.attempts[0]
    self.assertEqual(self._context, context)
    self.assertEqual(self.as_goals(*goal_names), goals)

  def test_execute_success(self):
    engine = self.RecordingEngine()
    result = engine.execute(self._context, self.as_goals('one', 'two'))
    self.assertEqual(0, result)
    self.assert_attempt(engine, 'one', 'two')

  def _throw(self, error):
    def throw():
      raise error
    return throw

  def test_execute_raise(self):
    engine = self.RecordingEngine(action=self._throw(TaskError()))
    result = engine.execute(self._context, self.as_goals('three'))
    self.assertEqual(1, result)
    self.assert_attempt(engine, 'three')

  def test_execute_code(self):
    engine = self.RecordingEngine(action=self._throw(TaskError(exit_code=42)))
    result = engine.execute(self._context, self.as_goals('four', 'five', 'six'))
    self.assertEqual(42, result)
    self.assert_attempt(engine, 'four', 'five', 'six')
