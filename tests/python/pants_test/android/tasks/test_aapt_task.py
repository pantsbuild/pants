# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.tasks.aapt_gen import AaptTask
from pants_test.android.test_android_base import TestAndroidBase


class TestAaptTask(TestAndroidBase):

  @classmethod
  def task_type(cls):
    return AaptTask

  # This just tests the AaptTask static/class methods. Any methods that need a task instance
  # are exercised in tests for AaptTask subclasses.
  def test_is_aapt_target(self):
    with self.android_binary() as android_binary:
      self.assertTrue(AaptTask.is_android_binary(android_binary))

  def test_not_aapt_target(self):
    with self.android_library() as android_library:
      self.assertFalse(AaptTask.is_android_binary(android_library))

  def test_package_path_translation(self):
    self.assertEqual(os.path.join('com', 'pants', 'example', 'tests'),
                     AaptTask.package_path('com.pants.example.tests'))

  def test_package_path(self):
    self.assertEqual('com', AaptTask.package_path('com'))
