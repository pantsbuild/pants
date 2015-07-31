# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.tasks.aapt_builder import AaptBuilder
from pants_test.android.test_android_base import TestAndroidBase, distribution


class TestAaptBuilder(TestAndroidBase):

  @classmethod
  def task_type(cls):
    return AaptBuilder

  def test_aapt_builder_smoke(self):
    task = self.create_task(self.context())
    task.execute()

  def test_creates_apk(self):
    with self.android_binary(target_name='example', package_name='org.pantsbuild.example') as apk:
      self.assertTrue(AaptBuilder.package_name(apk).endswith('.apk'))

  def test_unique_package_name(self):
    with self.android_binary(target_name='example', package_name='org.pantsbuild.example') as bin1:
      with self.android_binary(target_name='hello', package_name='org.pantsbuild.hello') as bin2:
        self.assertNotEqual(AaptBuilder.package_name(bin1), AaptBuilder.package_name(bin2))

  def test_render_args(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist)
        task = self.create_task(self.context())
        rendered_args = task._render_args(android_binary, 'res', ['classes.dex'])
        self.assertEquals(os.path.basename(rendered_args[0]), 'aapt')
        self.assertEquals(rendered_args[-1], 'classes.dex')

  def test_resource_order_in_args(self):
    with distribution() as dist:
      with self.android_resources(target_name='binary_resources') as res1:
        with self.android_resources(target_name='library_resources') as res2:
          with self.android_library(dependencies=[res2]) as library:
            with self.android_binary(dependencies=[res1, library]) as target:
              self.set_options(sdk_path=dist)
              task = self.create_task(self.context())

              res_dirs = [res1.resource_dir, res2.resource_dir]
              rendered_args = task._render_args(target, res_dirs, 'classes.dex')

              args_string = ' '.join(rendered_args)
              self.assertIn('--auto-add-overlay -S {} -S '
                            '{}'.format(res1.resource_dir, res2.resource_dir), args_string)
