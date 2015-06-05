# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.tasks.zipalign import Zipalign
from pants_test.android.test_android_base import TestAndroidBase, distribution


class TestZipalign(TestAndroidBase):
  """Test class for the Zipalign task."""

  @classmethod
  def task_type(cls):
    return Zipalign

  def test_zipalign_smoke(self):
    task = self.create_task(self.context())
    task.execute()

  def test_zipalign_binary(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist)
        task = self.create_task(self.context())
        target = android_binary
        self.assertEqual(task.zipalign_binary(target),
                         os.path.join(dist, 'build-tools', target.build_tools_version, 'zipalign'))

  def test_zipalign_out(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist)
        task = self.create_task(self.context())
        target = android_binary
        self.assertEqual(task.zipalign_out(target), os.path.join(task._distdir, target.name))

  def test_render_args(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist)
        task = self.create_task(self.context())
        target = android_binary
        expected_args = [os.path.join(dist, 'build-tools', target.build_tools_version, 'zipalign'),
                         '-f', '4', 'package/path',
                         os.path.join(task._distdir, target.name,
                                      '{0}.signed.apk'.format(target.manifest.package_name))]
        self.assertEqual(task._render_args('package/path', target), expected_args)
