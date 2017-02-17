# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from textwrap import dedent

from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdtemp
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.tasks.node_build import NodeBuild as NodeBuildTask
from pants.contrib.node.tasks.node_paths import NodePaths


class TestNodeBuild(TaskTestBase):

  @classmethod
  def task_type(cls):
    return NodeBuildTask

  def _run_test_and_get_products(self, node_modules_and_files=None):
    resolved_node_paths = NodePaths()
    for node_module, files in node_modules_and_files:
      tmp_dir = safe_mkdtemp()
      for f in files or []:
        shutil.copy(f, tmp_dir)
      resolved_node_paths.resolved(node_module, tmp_dir)
    task_context = self.context(target_roots=[node_modules_and_files[0][0]])
    task_context.products.safe_create_data(NodePaths, init_func=lambda: resolved_node_paths)
    task = self.create_task(task_context)
    task.execute()

    bundleable_js_product = task.context.products.get_data('bundleable_js')
    runtime_classpath_product = task.context.products.get_data('runtime_classpath')
    return bundleable_js_product, runtime_classpath_product, resolved_node_paths

  def _get_all_bundleable_js_path(self, bundleable_js_product, node_module):
    ret_value = []
    for _, abs_paths in bundleable_js_product[node_module].abs_paths():
      ret_value.extend(abs_paths)
    return ret_value

  def test_node_module(self):
    node_dependent_module_name = 'dependent_target'
    node_dependent_module = self.make_target(node_dependent_module_name, NodeModule)
    target_name = 'target_no_build'
    target = self.make_target(
      spec=target_name,
      target_type=NodeModule,
      dependencies=[node_dependent_module],
    )

    bundleable_js, runtime_classpath, node_paths = self._run_test_and_get_products(
      [(target, None), (node_dependent_module, None)])

    node_dependent_paths = self._get_all_bundleable_js_path(bundleable_js, node_dependent_module)
    self.assertEquals(1, len(node_dependent_paths))
    self.assertEquals(
      os.path.normpath(node_dependent_paths[0]),
      os.path.normpath(node_paths.node_path(node_dependent_module)))
    target_paths = self._get_all_bundleable_js_path(bundleable_js, target)
    self.assertEquals(1, len(target_paths))
    self.assertEquals(
      os.path.normpath(target_paths[0]),
      os.path.normpath(node_paths.node_path(target)))

    node_dependent_classpath = runtime_classpath.get_for_target(node_dependent_module)
    self.assertEquals(1, len(node_dependent_classpath))
    self.assertEquals(
      os.path.realpath(os.path.join(node_dependent_classpath[0][1], node_dependent_module_name)),
      os.path.realpath(node_paths.node_path(node_dependent_module)))
    target_classpaths = runtime_classpath.get_for_target(target)
    self.assertEquals(1, len(target_classpaths))
    self.assertEquals(
      os.path.realpath(os.path.join(target_classpaths[0][1], target_name)),
      os.path.realpath(node_paths.node_path(target)))

  def test_node_module_no_artifacts(self):
    node_dependent_module = self.make_target(
      spec=':dependent_target',
      target_type=NodeModule,
      dev_dependency=True)

    target = self.make_target(
      spec=':target_no_build',
      target_type=NodeModule,
      dependencies=[node_dependent_module],
      dev_dependency=True
    )
    bundleable_js, runtime_classpath, node_paths = self._run_test_and_get_products(
      [(target, None), (node_dependent_module, None)])

    self.assertFalse(len(bundleable_js))
    self.assertFalse(len(runtime_classpath.get_for_target(node_dependent_module)))
    self.assertFalse(len(runtime_classpath.get_for_target(target)))

  def test_run_build_script(self):
    package_json_file = self.create_file(
      'src/node/build_test/package.json',
      contents=dedent("""
        {
          "scripts": {
            "my_build": "mkdir myOutput; echo 'Hello, world!' >myOutput/output_file"
          }
        }
      """))
    target = self.make_target(
      spec='src/node/build_test',
      target_type=NodeModule,
      sources=['package.json'],
      build_script='my_build',
      output_dir='myOutput')
    bundleable_js, runtime_classpath, node_paths = self._run_test_and_get_products([
      (target, [package_json_file])])

    target_paths = self._get_all_bundleable_js_path(bundleable_js, target)
    target_classpaths = runtime_classpath.get_for_target(target)

    self.assertEquals(
      os.path.realpath(target_paths[0]),
      os.path.realpath(os.path.join(target_classpaths[0][1], 'build_test')))
    self.assertTrue(os.path.realpath(target_paths[0]).endswith('myOutput'))
    self.assertEquals(set(os.listdir(target_paths[0])), set(['output_file']))
    with open(os.path.join(target_paths[0], 'output_file')) as f:
      self.assertEquals(f.read(), 'Hello, world!\n')

  def test_run_non_existing_script(self):
    package_json_file = self.create_file(
      'src/node/build_test/package.json', contents='{}')
    build_script = 'my_non_existing_build_scirpt'
    target = self.make_target(
      spec='src/node/build_test',
      target_type=NodeModule,
      sources=['package.json'],
      build_script=build_script)
    with self.assertRaisesRegexp(TaskError, build_script):
      self._run_test_and_get_products([(target, [package_json_file])])

  def test_run_no_output_dir(self):
    package_json_file = self.create_file(
      'src/node/build_test/package.json',
      contents=dedent("""
        {
          "scripts": {
            "my_build": "echo 'Hello, world!'"
          }
        }
      """))
    output_dir='not_exist'
    target = self.make_target(
      spec='src/node/build_test',
      target_type=NodeModule,
      sources=['package.json'],
      build_script='my_build',
      output_dir=output_dir)
    with self.assertRaisesRegexp(TaskError, output_dir):
      self._run_test_and_get_products([(target, [package_json_file])])
