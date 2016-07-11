# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from mock import patch
from pants.base.exceptions import TestFailedTaskError
from pants.util.timeout import TimeoutReached
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.node.subsystems.resolvers.npm_resolver import NpmResolver
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_test import NodeTest as NodeTestTarget
from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_resolve import NodeResolve
from pants.contrib.node.tasks.node_test import NodeTest as NodeTestTask


class NodeTestTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return NodeTestTask

  def setUp(self):
    super(NodeTestTest, self).setUp()
    NodeResolve.register_resolver_for_type(NodeModule, NpmResolver)

  def tearDown(self):
    super(NodeTestTest, self).tearDown()
    NodeResolve._clear_resolvers()

  def _create_node_module_target(self):
    self.create_file('src/node/test_node_test/package.json', contents=dedent("""
      {
          "name": "pantsbuild.pants.test.test_node_test",
          "version": "0.0.0",
          "scripts": {
            "test": "echo 0"
          }
      }
    """))
    return self.make_target(spec='src/node/test_node_test',
                            target_type=NodeModule,
                            sources=['package.json'])

  def _resolve_node_module_and_create_tests_task(self, node_module_target, test_targets,
                                                 passthru_args=None):
    context = self.context(target_roots=test_targets, passthru_args=passthru_args)

    # Fake resolving so self.context.products.get_data(NodePaths) is populated for NodeTestTask.
    node_module_target_root = os.path.join(self.build_root, node_module_target.address.spec_path)
    node_paths = context.products.get_data(NodePaths, init_func=NodePaths)
    node_paths.resolved(node_module_target, node_module_target_root)

    return self.create_task(context)

  def test_timeout(self):
    target = self._create_node_module_target()

    test_target = self.make_target(spec='src/node/test_node_test:test',
                                   target_type=NodeTestTarget,
                                   dependencies=[target],
                                   timeout=5)

    task = self._resolve_node_module_and_create_tests_task(target, [test_target])

    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      mock_timeout().__exit__.side_effect = TimeoutReached(5)

      with self.assertRaises(TestFailedTaskError):
        task.execute()

      # Ensures that Timeout is instantiated with a 5 second timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (5,))

  def test_timeout_multiple_targets(self):
    target = self._create_node_module_target()

    test_target1 = self.make_target(spec='src/node/test_node_test:test1',
                                    target_type=NodeTestTarget,
                                    dependencies=[target],
                                    timeout=5)
    test_target2 = self.make_target(spec='src/node/test_node_test:test2',
                                    target_type=NodeTestTarget,
                                    dependencies=[target],
                                    timeout=5)

    task = self._resolve_node_module_and_create_tests_task(target, [test_target1, test_target2])

    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      mock_timeout().__exit__.side_effect = TimeoutReached(5)

      with self.assertRaises(TestFailedTaskError) as cm:
        task.execute()

      # Verify that only the first target is in the failed_targets list, not all test targets.
      self.assertEqual(len(cm.exception.failed_targets), 1)
      self.assertEqual(cm.exception.failed_targets[0].address.spec, 'src/node/test_node_test:test1')

      # Ensures that Timeout is instantiated with a 5 second timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (5,))
