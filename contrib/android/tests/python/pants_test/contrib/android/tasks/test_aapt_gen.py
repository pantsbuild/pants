# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.contrib.android.test_android_base import TestAndroidBase, distribution

from pants.contrib.android.tasks.aapt_gen import AaptGen


class TestAaptGen(TestAndroidBase):

  @classmethod
  def task_type(cls):
    return AaptGen

  def test_aapt_gen_smoke(self):
    task = self.create_task(self.context())
    task.execute()

  def test_relative_genfile(self):
    with self.android_binary(package_name='org.pantsbuild.examples.hello') as binary:
      self.assertEqual(AaptGen._relative_genfile(binary),
                       os.path.join('org', 'pantsbuild', 'examples', 'hello', 'R.java'))

  def test_create_sdk_jar_deps(self):
    with distribution() as dist:
      with self.android_binary(target_name='binary1', target_sdk='18') as binary1:
        with self.android_binary(target_name='binary2', target_sdk='19') as binary2:
          self.set_options(sdk_path=dist)
          task = self.create_task(self.context())
          targets = [binary1, binary2]
          task.create_sdk_jar_deps(targets)
          self.assertNotEquals(task._jar_library_by_sdk['19'], task._jar_library_by_sdk['18'])

  def test_create_sdk_dependency_injection(self):
    with distribution() as dist:
      with self.android_binary(target_name='binary1', target_sdk='18') as binary1:
        with self.android_binary(target_name='binary2', target_sdk='19') as binary2:
          self.set_options(sdk_path=dist)
          task = self.create_task(self.context())
          targets = [binary1, binary2]
          task.create_sdk_jar_deps(targets)
          self.assertIn(task._jar_library_by_sdk['18'], binary1.dependencies)
          self.assertIn(task._jar_library_by_sdk['19'], binary2.dependencies)
          self.assertNotIn(task._jar_library_by_sdk['19'], binary1.dependencies)

  def test_aapt_out_different_sdk(self):
    with self.android_binary(target_name='binary1', target_sdk='18') as binary1:
      with self.android_binary(target_name='binary2', target_sdk='19') as binary2:
        task = self.create_task(self.context())
        self.assertNotEqual(task.aapt_out(binary1), task.aapt_out(binary2))

  def test_aapt_out_same_sdk(self):
    with self.android_binary(target_name='binary1', target_sdk='19') as binary1:
      with self.android_binary(target_name='binary2', target_sdk='19') as binary2:
        task = self.create_task(self.context())
        self.assertEquals(task.aapt_out(binary1), task.aapt_out(binary2))

  def test_aapt_tool(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist, build_tools_version='20.0.0')
        task = self.create_task(self.context())
        aapt_tool = task.aapt_tool(android_binary)
        self.assertEquals(os.path.basename(os.path.dirname(aapt_tool)), '20.0.0')
        self.assertEquals(os.path.basename(aapt_tool), 'aapt')

  def test_android_tool(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist, target_sdk='18')
        task = self.create_task(self.context())
        android_jar = task.android_jar(android_binary)
        self.assertEquals(os.path.basename(os.path.dirname(android_jar)), 'android-18')
        self.assertEquals(os.path.basename(android_jar), 'android.jar')

  def test_render_args(self):
    with distribution() as dist:
      with self.android_resources() as resources:
        with self.android_binary(dependencies=[resources]) as binary:
          self.set_options(sdk_path=dist)
          task = self.create_task(self.context())
          rendered_args = task._render_args(binary, binary.manifest, [resources.resource_dir])
        self.assertEquals(os.path.basename(rendered_args[0]), 'aapt')

  def test_priority_order_in_render_args(self):
    with distribution() as dist:
      with self.android_resources(target_name='binary_resources') as res1:
        with self.android_resources(target_name='library_resources') as res2:
          with self.android_library(dependencies=[res2]) as library:
            with self.android_binary(dependencies=[res1, library]) as binary:
              self.set_options(sdk_path=dist)
              task = self.create_task(self.context())

              res_dirs = [res1.resource_dir, res2.resource_dir]
              rendered_args = task._render_args(binary, binary.manifest, res_dirs)
              args_string = ' '.join(rendered_args)
              self.assertIn('--auto-add-overlay -S {} -S '
                            '{}'.format(res1.resource_dir, res2.resource_dir), args_string)

  def test_render_args_force_ignored(self):
    with distribution() as dist:
      with self.android_resources() as resources:
        with self.android_binary(dependencies=[resources]) as binary:
          ignored = '!picasa.ini:!*~:BUILD*'
          self.set_options(sdk_path=dist, ignored_assets=ignored)
          task = self.create_task(self.context())
          rendered_args = task._render_args(binary, binary.manifest, [resources.resource_dir])
          self.assertIn(ignored, rendered_args)

  def test_create_target(self):
    with distribution() as dist:
      with self.android_library() as library:
        with self.android_binary(dependencies=[library]) as android_binary:
          self.set_options(sdk_path=dist)
          task = self.create_task(self.context())
          targets = [android_binary]
          task.create_sdk_jar_deps(targets)
          created_target = task.create_target(android_binary, library)
          self.assertEqual(created_target.derived_from, library)
          self.assertTrue(created_target.is_synthetic)
