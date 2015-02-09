# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.tasks.zipalign import Zipalign
from pants_test.android.test_android_base import TestAndroidBase


class TestZipalign(TestAndroidBase):
  """Test class for the Zipalign task."""

  @classmethod
  def task_type(cls):
    return Zipalign

  def test_zipalign_smoke(self):
    task = self.prepare_task(build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser)
    task.execute()


  def test_zipalign_binary(self):
    with self.distribution() as dist:
      with self.android_binary() as android_binary:
        task = self.prepare_task(args=['--test-sdk-path={0}'.format(dist)],
                                   build_graph=self.build_graph,
                                   build_file_parser=self.build_file_parser)
        target = android_binary
        self.assertEqual(task.zipalign_binary(target),
                         os.path.join(dist, 'build-tools', target.build_tools_version, 'zipalign'))

  def test_zipalign_out(self):
    with self.distribution() as dist:
      with self.android_binary() as android_binary:
        task = self.prepare_task(args=['--test-sdk-path={0}'.format(dist)],
                                 build_graph=self.build_graph,
                                 build_file_parser=self.build_file_parser)
        target = android_binary
        self.assertEqual(task.zipalign_out(target), os.path.join(task._distdir, target.name))

  def test_render_args(self):
    with self.distribution() as dist:
      with self.android_binary() as android_binary:
        task = self.prepare_task(args=['--test-sdk-path={0}'.format(dist)],
                                 build_graph=self.build_graph,
                                 build_file_parser=self.build_file_parser)
        target = android_binary
        expected_args = [os.path.join(dist, 'build-tools', target.build_tools_version, 'zipalign'),
                          '-f', '4', 'package/path',
                          os.path.join(task._distdir, target.name,
                                       '{0}.signed.apk'.format(target.name))]
        self.assertEqual(task._render_args('package/path', target), expected_args)
