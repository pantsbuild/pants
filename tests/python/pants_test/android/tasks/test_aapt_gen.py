# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.tasks.aapt_gen import AaptGen
from pants_test.android.test_android_base import TestAndroidBase, distribution


class TestAaptGen(TestAndroidBase):
  """Test the methods in pants.backend.android.tasks.aapt_gen."""

  @classmethod
  def task_type(cls):
    return AaptGen

  def test_android_library_target(self):
    pass

  def test_aapt_gen_smoke(self):
    task = self.create_task(self.context())
    task.execute()

  def test_calculate_genfile(self):
    self.assertEqual(AaptGen._calculate_genfile('com.pants.examples.hello'),
                     os.path.join('com', 'pants', 'examples', 'hello', 'R.java'))

  def test_aapt_out(self):
    task = self.create_task(self.context())
    outdir = task.aapt_out('19')
    self.assertEqual(os.path.join(task.workdir, '19'), outdir)

  def test_aapt_tool(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist)
        task = self.create_task(self.context())
        target = android_binary
        self.assertEqual(task.aapt_tool(target.build_tools_version),
                         os.path.join(dist, 'build-tools', target.build_tools_version, 'aapt'))

  def test_android_tool(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist)
        task = self.create_task(self.context())
        target = android_binary
        # Android jar is copied under the buildroot to comply with classpath rules.
        jar_folder = os.path.join(task.workdir, 'platforms',
                                  'android-{}'.format(target.manifest.target_sdk), 'android.jar')
        self.assertEqual(task.android_jar_tool(target.manifest.target_sdk), jar_folder)


  def test_render_args(self):
    with distribution() as dist:
      with self.android_resources() as android_resources:
        with self.android_binary(dependencies=[android_resources]) as binary:
          self.set_options(sdk_path=dist)
          task = self.create_task(self.context())
          target = binary
          expected_args = [task.aapt_tool(target.build_tools_version),
                           'package', '-m', '-J', task.workdir,
                           '-M', target.manifest.path,
                           '--auto-add-overlay',
                           '-S', android_resources.resource_dir,
                           '-I', task.android_jar_tool(target.manifest.target_sdk),
                           '--ignore-assets', task.ignored_assets]
          self.assertEqual(expected_args, task._render_args(target, target.target_sdk,
                                                            [android_resources.resource_dir],
                                                            task.workdir))


  def test_render_args_with_android_library(self):
    with distribution() as dist:
      with self.android_resources(name='binary_resources') as resources1:
        with self.android_resources(name='library_resources') as resources2:
          with self.android_library(dependencies=[resources2]) as library:
            with self.android_binary(dependencies=[resources1, library]) as binary:
              self.set_options(sdk_path=dist)
              task = self.create_task(self.context())
              # Show that all dependent lib and resources are processed with the binary's target sdk
              # and that the resource dirs are scanned in reverse order of collection.
              expected_args = [task.aapt_tool(binary.build_tools_version),
                               'package', '-m', '-J', task.workdir,
                               '-M', resources1.manifest.path,
                               '--auto-add-overlay',
                               '-S', resources1.resource_dir,
                               '-S', resources2.resource_dir,
                               '-I', task.android_jar_tool(binary.manifest.target_sdk),
                               '--ignore-assets', task.ignored_assets]
              self.assertEqual(expected_args,
                               task._render_args(resources1, binary.target_sdk,
                                                 [resources2.resource_dir, resources1.resource_dir],
                                                 task.workdir))

  def test_render_args_force_args(self):
    with distribution() as dist:
      with self.android_resources() as android_resources:
        with self.android_binary(dependencies=[android_resources]) as binary:
          build_tools = '20.0.0'
          sdk = '19'
          ignored = '!picasa.ini:!*~:BUILD*'
          self.set_options(sdk_path=dist, build_tools_version=build_tools, target_sdk=sdk,
                           ignored_assets=ignored)
          task = self.create_task(self.context())
          target = binary
          expected_args = [task.aapt_tool(build_tools),
                           'package', '-m', '-J', task.workdir,
                           '-M', target.manifest.path,
                           '--auto-add-overlay',
                           '-S', android_resources.resource_dir,
                           '-I', task.android_jar_tool(sdk),
                           '--ignore-assets', ignored]
          self.assertEqual(expected_args, task._render_args(target, target.target_sdk,
                                                            [android_resources.resource_dir],
                                                            task.workdir))

  def test_create_target(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist)
        task = self.create_task(self.context())
        targets = [android_binary]
        task.create_sdk_jar_deps(targets)
        created_target = task.create_target(android_binary, '19')
        self.assertEqual(created_target.derived_from, android_binary)
        self.assertTrue(created_target.is_synthetic)
