# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import pytest
import tempfile

from contextlib import closing, contextmanager
from zipfile import ZipFile

from twitter.common.dirutil import safe_rmtree, touch

from twitter.pants.base.context_utils import create_context
from twitter.pants.tasks.detect_duplicates import DuplicateDetector
from twitter.pants.tasks.task_error import TaskError
from twitter.pants.tasks.test_base import TaskTest


class DuplicateDetectorTest(TaskTest):
  def setUp(self):
    self.base_dir = tempfile.mkdtemp()

    def generate_path(name):
      return os.path.join(self.base_dir, name)

    test_class_path = generate_path('com/twitter/Test.class')
    duplicate_class_path = generate_path('com/twitter/commons/Duplicate.class')
    unique_class_path = generate_path('org/apache/Unique.class')

    touch(test_class_path)
    touch(duplicate_class_path)
    touch(unique_class_path)

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

      jars = []
      jars.append(test_jar)
      jars.append(jar_with_duplicates)
      jars.append(jar_without_duplicates)
      yield jars

    with jars() as jars:
      self.path_with_duplicates = [jars[0], jars[1]]
      self.path_without_duplicates = [jars[0], jars[2]]

  def tearDown(self):
    safe_rmtree(self.base_dir)

  def test_duplicate_found(self):
    options = {'fail_fast': False}
    task = DuplicateDetector(create_context(options=options))
    self.assertTrue(task._is_conflicts(self.path_with_duplicates, None))

  def test_duplicate_not_found(self):
    options = {'fail_fast': False}
    task = DuplicateDetector(create_context(options=options))
    self.assertFalse(task._is_conflicts(self.path_without_duplicates, None))

  def test_fail_fast_error_raised(self):
    options = {'fail_fast': True}
    task = DuplicateDetector(create_context(options=options))
    with pytest.raises(TaskError):
      task._is_conflicts(self.path_with_duplicates, None)
