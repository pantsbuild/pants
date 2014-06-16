# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.task import Task
from pants.engine.linear_engine import LinearEngine

from pants_test.base_test import BaseTest
from pants_test.engine.base_engine_test import EngineTestBase


class LinearEngineTest(EngineTestBase, BaseTest):
  def setUp(self):
    super(LinearEngineTest, self).setUp()

    self._context = self.context(options=dict(explain=False, no_lock=False))
    self.assertTrue(self._context.is_unlocked())

    self.engine = LinearEngine()
    self.recorded_actions = []

  def tearDown(self):
    self.assertTrue(self._context.is_unlocked())
    super(LinearEngineTest, self).tearDown()

  def construct_action(self, tag):
    return 'construct', tag, self._context

  def prepare_action(self, tag):
    return 'prepare', tag, self._context

  def execute_action(self, tag):
    return 'execute', tag, self._context

  def record(self, tag):
    class RecordingTask(Task):
      def __init__(me, context, workdir):
        super(RecordingTask, me).__init__(context, workdir)
        self.recorded_actions.append(self.construct_action(tag))

      def prepare(me):
        self.recorded_actions.append(self.prepare_action(tag))

      def execute(me):
        self.recorded_actions.append(self.execute_action(tag))

    return RecordingTask

  def install_goal(self, name, dependencies=None, phase=None):
    return self.installed_goal(name,
                               action=self.record(name),
                               dependencies=dependencies,
                               phase=phase)

  def test_linearization(self):
    self.install_goal('resolve')
    self.install_goal('javac', dependencies=['resolve'], phase='compile')
    self.install_goal('checkstyle', phase='compile')
    self.install_goal('resources')
    self.install_goal('test', dependencies=['compile', 'resources'])

    result = self.engine.execute(self._context, self.as_phases('test'))
    self.assertEqual(0, result)

    # TODO(John Sirois): Going forward only the prepare_actions should be tested for ordering, the
    # constructions should be early an in unspecified order
    expected = [self.construct_action('test'),
                self.prepare_action('test'),
                self.construct_action('resources'),
                self.prepare_action('resources'),
                self.construct_action('checkstyle'),
                self.prepare_action('checkstyle'),
                self.construct_action('javac'),
                self.prepare_action('javac'),
                self.construct_action('resolve'),
                self.prepare_action('resolve'),
                self.execute_action('resolve'),
                self.execute_action('javac'),
                self.execute_action('checkstyle'),
                self.execute_action('resources'),
                self.execute_action('test')]
    self.assertEqual(expected, self.recorded_actions)
