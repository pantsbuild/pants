# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tempfile
from contextlib import contextmanager

from pants.backend.jvm.tasks.detect_duplicates import DuplicateDetector
from pants.base.exceptions import TaskError
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_rmtree, touch
from pants_test.tasks.task_test_base import TaskTestBase


class DuplicateDetectorTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return DuplicateDetector

  def setUp(self):
    super(DuplicateDetectorTest, self).setUp()

    base_dir = tempfile.mkdtemp()
    self.addCleanup(safe_rmtree, base_dir)

    def generate_path(name):
      return os.path.join(base_dir, name)

    test_class_path = generate_path('com/twitter/Test.class')
    duplicate_class_path = generate_path('com/twitter/commons/Duplicate.class')
    unique_class_path = generate_path('org/apache/Unique.class')
    unicode_class_path = generate_path('cucumber/api/java/zh_cn/假如.class')

    touch(test_class_path)
    touch(duplicate_class_path)
    touch(unique_class_path)
    touch(unicode_class_path)

    def generate_jar(path, *class_name):
      with open_zip(generate_path(path), 'w') as zipfile:
        for clazz in class_name:
          zipfile.write(clazz)
        return zipfile.filename

    @contextmanager
    def jars():
      test_jar = generate_jar('test.jar', test_class_path, duplicate_class_path)
      jar_with_duplicates = generate_jar('dups.jar', duplicate_class_path, unique_class_path)
      jar_without_duplicates = generate_jar('no_dups.jar', unique_class_path)
      jar_with_unicode = generate_jar('unicode_class.jar', unicode_class_path)

      yield test_jar, jar_with_duplicates, jar_without_duplicates, jar_with_unicode

    with jars() as jars:
      test_jar, jar_with_duplicates, jar_without_duplicates, jar_with_unicode = jars
      self.path_with_duplicates = {
          'com/twitter/Test.class': {test_jar},
          'com/twitter/commons/Duplicate.class': {test_jar, jar_with_duplicates},
          'org/apache/Unique.class': {jar_with_duplicates},
          'cucumber/api/java/zh_cn/假如.class': {jar_with_unicode},
      }
      self.path_without_duplicates = {
          'com/twitter/Test.class': {test_jar},
          'com/twitter/commons/Duplicate.class': {test_jar},
          'org/apache/Unique.class': {jar_without_duplicates},
          'cucumber/api/java/zh_cn/假如.class': {jar_with_unicode},
      }

  def execute_detect_duplicates(self, fail_fast):
    self.set_options(fail_fast=fail_fast, excludes=[], max_dups=10)
    context = self.context()
    task = self.create_task(context)
    task.execute()
    return task

  def test_duplicate_found(self):
    task = self.execute_detect_duplicates(fail_fast=False)
    self.assertTrue(task._is_conflicts(self.path_with_duplicates, binary_target=None))

  def test_duplicate_not_found(self):
    task = self.execute_detect_duplicates(fail_fast=False)
    self.assertFalse(task._is_conflicts(self.path_without_duplicates, binary_target=None))

  def test_fail_fast_error_raised(self):
    task = self.execute_detect_duplicates(fail_fast=True)
    with self.assertRaises(TaskError):
      task._is_conflicts(self.path_with_duplicates, binary_target=None)
