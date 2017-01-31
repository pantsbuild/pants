# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

#import json
import os
#import string
#from textwrap import dedent

#from pants.build_graph.target import Target
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch
from pants_test.tasks.task_test_base import TaskTestBase
#from pants.contrib.node.subsystems.node_distribution import NodeDistribution
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.tasks.node_bundle import NodeBundle
from pants.contrib.node.tasks.node_paths import NodePaths


class TestNodeBundle(TaskTestBase):

  @classmethod
  def task_type(cls):
    return NodeBundle

  def test_node_deployable_bundle(self):
    target_path = 'fake/target'
    target_name = 'myTarget'
    with temporary_dir() as tmp_dir:
      touch(os.path.join(tmp_dir, 'a'))
      target = self.make_target(':'.join([target_path, target_name]), NodeModule)
      resolved_node_paths = NodePaths()
      resolved_node_paths.resolved(target, tmp_dir)
      task_context = self.context(target_roots=[target])
      task_context.products.safe_create_data(NodePaths, init_func=lambda: resolved_node_paths)
      task = self.create_task(task_context)

      task.execute()
      product = task_context.products.get('deployable_archives')
      self.assertIsNotNone(product)
      self.assertFalse(product.empty())

      product_data = product.get(target)
      self.assertIsNotNone(product_data)
      product_basedir = product_data.keys()[0]
      self.assertEquals(product_data[product_basedir], ['{}.tar.gz'.format(target_name)])
