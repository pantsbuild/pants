# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

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
    self.construct_actions = []
    self.prepare_actions = []
    self.execute_actions = []

  def tearDown(self):
    self.assertTrue(self._context.is_unlocked())
    super(RoundEngineTest, self).tearDown()

  def construct_action(self, tag):
    return 'construct', tag, self._context

  def prepare_action(self, tag):
    return 'prepare', tag, self._context

  def execute_action(self, tag):
    return 'execute', tag, self._context

  def record(self, tag, product_type=None, prepare=None):
    class RecordingTask(Task):
      def __init__(me, context, workdir):
        super(RecordingTask, me).__init__(context, workdir)
        self.construct_actions.append(self.construct_action(tag))

      @classmethod
      def product_type(cls):
        if product_type:
          return [product_type]

      def prepare(me, round_manager):
        if prepare and round_manager:
          for p in prepare:
            round_manager.require_data(p)
        self.prepare_actions.append(self.prepare_action(tag))

      def execute(me):
        self.execute_actions.append(self.execute_action(tag))

    return RecordingTask

  def install_goal(self, name, product_type=None, phase=None, test_namespace=None, prepare=None):
    return self.installed_goal(name=name,
                               action=self.record(name, product_type, prepare),
                               dependencies=None,
                               phase=phase,
                               test_namespace=test_namespace)

  def test_round_engine(self):
    self.install_goal('prepare', 'resources_by_target', 'resources', False, ['exclusives_groups'])
    self.install_goal('bootstrap-jvm-tools', 'jvm_build_tools', 'bootstrap', False)
    self.install_goal('junit', 'junit_products', 'test', False, ['classes_by_target'])
    self.install_goal('thrift', 'classes_by_source', 'gen', False,
                      ['jvm_build_tools_classpath_callbacks', 'jvm_build_tools'])
    self.install_goal('ivy', 'ivy_jar_products', 'resolve', False, ['resources_by_target'])
    self.install_goal('scrooge', 'classes_by_source', 'gen', False,
                      ['jvm_build_tools_classpath_callbacks', 'jvm_build_tools'])
    self.install_goal('protoc', 'classes_by_source', 'gen', False,
                      ['jvm_build_tools_classpath_callbacks', 'jvm_build_tools'])
    self.install_goal('antlr',  'classes_by_source', 'gen', False,
                      ['jvm_build_tools_classpath_callbacks', 'jvm_build_tools'])
    self.install_goal('jvm', 'classes_by_target', 'compile', False, ['ivy_jar_products'])
    self.install_goal('check-exclusives',  'exclusives_groups', 'check-exclusives', False,
                      ['classes_by_source'])

    phases = self.as_phases_without_namespace('test')
    self.engine.attempt(self._context, phases)

    actions = [
      'bootstrap-jvm-tools', 'thrift', 'scrooge', 'protoc', 'antlr', 'check-exclusives',
      'prepare', 'ivy', 'jvm', 'junit']
    expected_construct_actions = [self.construct_action(action) for action in actions]
    expected_prepare_actions = [self.prepare_action(action) for action in reversed(actions)]
    expected_execute_actions = [self.execute_action(action) for action in actions]

    self.assertEqual(sorted(expected_construct_actions), sorted(set(self.construct_actions)))
    self.assertEqual(expected_prepare_actions, self.prepare_actions)
    self.assertEqual(expected_execute_actions, self.execute_actions)
