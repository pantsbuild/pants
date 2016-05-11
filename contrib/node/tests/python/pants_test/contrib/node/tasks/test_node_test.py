# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.base.exceptions import TestFailedTaskError
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

  def test_timeout(self):
    self.create_file('src/node/too_long/package.json', contents=dedent("""
      {
          "name": "pantsbuild.pants.test.too_long",
          "version": "0.0.0",
          "scripts": {
            "test": "sleep 10"
          }
      }
    """))
    too_long_target = self.make_target(spec='src/node/too_long',
                                       target_type=NodeModule,
                                       sources=['package.json'])

    too_long_target_test = self.make_target(spec='src/node/too_long:test',
                                            target_type=NodeTestTarget,
                                            dependencies=[too_long_target])

    # Passing timeout=5 to make_target above gives an UninitializedSubsystemError
    # about Subsystem "UnknownArguments", just set it directly.
    too_long_target_test.timeout = 5

    context = self.context(target_roots=[too_long_target_test])

    # Fake resolving so self.context.products.get_data(NodePaths) is populated for NodeTestTask
    too_long_target_root = os.path.join(self.build_root, too_long_target.address.spec_path)
    node_paths = context.products.get_data(NodePaths, init_func=NodePaths)
    node_paths.resolved(too_long_target, too_long_target_root)

    task = self.create_task(context)

    with self.assertRaises(TestFailedTaskError):
      task.execute()
