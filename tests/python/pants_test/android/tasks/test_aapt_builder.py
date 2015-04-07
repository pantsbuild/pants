# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.tasks.aapt_builder import AaptBuilder
from pants.util.contextutil import temporary_dir
from pants_test.android.test_android_base import TestAndroidBase, distribution


class TestAaptBuilder(TestAndroidBase):
  """Test the methods in pants.backend.android.tasks.aapt_gen."""

  @classmethod
  def task_type(cls):
    return AaptBuilder

  def test_aapt_builder_smoke(self):
    task = self.create_task(self.context())
    task.execute()

  def test_render_args(self):
    with distribution() as dist:
      with temporary_dir() as temp:
        with self.android_binary() as android_binary:
          self.set_options(sdk_path=dist)
          task = self.create_task(self.context())
          target = android_binary
          package_name = '{0}.unsigned.apk'.format(target.manifest.package_name)
          expected_args = [task.aapt_tool(target.build_tools_version),
                           'package', '-f',
                           '-M', target.manifest.path,
                           '--auto-add-overlay',
                           '-S', 'res/directory',
                           '-I', task.android_jar_tool(target.manifest.target_sdk),
                           '--ignore-assets', task.ignored_assets,
                           '-F', os.path.join(task.workdir, package_name),
                           temp]
          self.assertEqual(expected_args, task._render_args(target, ['res/directory'], [temp]))
