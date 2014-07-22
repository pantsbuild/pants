# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import closing, contextmanager
import os
import tempfile
from zipfile import ZipFile

import pytest

from pants.backend.jvm.tasks.detect_duplicates import DuplicateDetector
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_rmtree, touch
from pants_test.base.context_utils import create_context
from pants_test.tasks.test_base import TaskTest


class DuplicateDetectorTest(TaskTest):
  def setUp(self):
    self.base_dir = tempfile.mkdtemp()

    def generate_path(name):
      return os.path.join(self.base_dir, name)

    test_class_path = generate_path('com/twitter/Test.class')
    duplicate_class_path = generate_path('com/twitter/commons/Duplicate.class')
    unique_class_path = generate_path('org/apache/Unique.class')
    unicode_class_path = generate_path('cucumber/api/java/zh_cn/假如.class')

    touch(test_class_path)
    touch(duplicate_class_path)
    touch(unique_class_path)
    touch(unicode_class_path)

    def generate_jar(path, *class_name):
      with closing(ZipFile(generate_path(path), 'w')) as zipfile:
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
          'com/twitter/Test.class': set([test_jar]),
          'com/twitter/commons/Duplicate.class': set([test_jar, jar_with_duplicates]),
          'org/apache/Unique.class': set([jar_with_duplicates]),
          'cucumber/api/java/zh_cn/假如.class' : set([jar_with_unicode]),
      }
      self.path_without_duplicates = {
          'com/twitter/Test.class': set([test_jar]),
          'com/twitter/commons/Duplicate.class': set([test_jar]),
          'org/apache/Unique.class': set([jar_without_duplicates]),
          'cucumber/api/java/zh_cn/假如.class' : set([jar_with_unicode]),
      }

  def tearDown(self):
    safe_rmtree(self.base_dir)

  def test_duplicate_found(self):
    options = {'fail_fast': False, 'excludes': None, 'max_dups' : 10}
    task = DuplicateDetector(create_context(options=options), workdir=None)
    self.assertTrue(task._is_conflicts(self.path_with_duplicates, binary_target=None))

  def test_duplicate_not_found(self):
    options = {'fail_fast': False, 'excludes': None, 'max_dups' : 10}
    task = DuplicateDetector(create_context(options=options), workdir=None)
    self.assertFalse(task._is_conflicts(self.path_without_duplicates, binary_target=None))

  def test_fail_fast_error_raised(self):
    options = {'fail_fast': True, 'excludes': None, 'max_dups' : 10}
    task = DuplicateDetector(create_context(options=options), workdir=None)
    with pytest.raises(TaskError):
      task._is_conflicts(self.path_with_duplicates, binary_target=None)
