# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.base.exceptions import TargetDefinitionException
from pants.goal.products import MultipleRootedProducts
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.node.targets.node_bundle import NodeBundle
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.tasks.node_bundle import NodeBundle as NodeBundleTask
from pants.contrib.node.tasks.node_paths import NodePaths


class TestNodeBundle(TaskTestBase):

  target_path = 'fake/target'
  target_name = 'myTarget'
  target_name_full = ':'.join([target_path, target_name])
  node_module_target_name = 'some_node_module'
  node_module_target_name_full = ':'.join([target_path, node_module_target_name])
  node_module_target_name_2 = 'some_other_node_module'
  node_module_target_name_full_2 = ':'.join([target_path, node_module_target_name_2])

  @classmethod
  def task_type(cls):
    return NodeBundleTask

  def test_node_deployable_bundle(self):
    with temporary_dir() as tmp_dir:
      touch(os.path.join(tmp_dir, 'a'))
      node_module_target = self.make_target(self.node_module_target_name_full, NodeModule)

      target = self.make_target(
        self.target_name_full, NodeBundle,
        node_module=self.node_module_target_name_full,
        dependencies=[node_module_target])

      bundleable_js_product = defaultdict(MultipleRootedProducts)
      bundleable_js_product[node_module_target].add_abs_paths(tmp_dir, [tmp_dir])
      task_context = self.context(target_roots=[target])
      task_context.products.safe_create_data(
        'bundleable_js', init_func=lambda: bundleable_js_product)
      task = self.create_task(task_context)

      task.execute()
      product = task_context.products.get('deployable_archives')
      self.assertIsNotNone(product)
      self.assertFalse(product.empty())

      product_data = product.get(target)
      self.assertIsNotNone(product_data)
      product_basedir = product_data.keys()[0]
      self.assertEquals(product_data[product_basedir], ['{}.tar.gz'.format(self.target_name)])

  def test_no_dependencies_for_node_bundle(self):
    with temporary_dir() as tmp_dir:
      with temporary_dir() as tmp_dir_2:
        touch(os.path.join(tmp_dir, 'a'))
        node_module_target = self.make_target(self.node_module_target_name_full, NodeModule)
        node_module_target_2 = self.make_target(self.node_module_target_name_full_2, NodeModule)

        target = self.make_target(
          self.target_name_full, NodeBundle,
          node_module=self.node_module_target_name_full,
          dependencies=[node_module_target, node_module_target_2],)

        resolved_node_paths = NodePaths()
        resolved_node_paths.resolved(node_module_target, tmp_dir)
        resolved_node_paths.resolved(node_module_target_2, tmp_dir_2)
        task_context = self.context(target_roots=[target])
        task_context.products.safe_create_data(NodePaths, init_func=lambda: resolved_node_paths)
        task = self.create_task(task_context)

        self.assertRaises(TargetDefinitionException, task.execute)

  def test_no_zip_for_archive(self):
    with self.assertRaisesRegexp(TargetDefinitionException, 'zip'):
      NodeBundle(node_module=self.node_module_target_name_full, archive='zip')

  def test_require_node_module_for_bundle(self):
    with self.assertRaisesRegexp(TargetDefinitionException, 'node_module'):
      NodeBundle()
