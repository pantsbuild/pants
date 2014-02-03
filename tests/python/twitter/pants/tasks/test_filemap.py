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
from textwrap import dedent

from twitter.pants.tasks.filemap import Filemap

from . import ConsoleTaskTest


class FilemapTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Filemap

  @classmethod
  def setUpClass(cls):
    super(FilemapTest, cls).setUpClass()

    def create_target(path, name, *files):
      for f in files:
        cls.create_file(os.path.join(path, f), '')

      cls.create_target(path, dedent('''
          python_library(name='%s',
            sources=[%s]
          )
          ''' % (name, ','.join(repr(f) for f in files))))

    cls.create_target('common', 'source_root.here(python_library)')
    create_target('common/a', 'a', 'one.py')
    create_target('common/b', 'b', 'two.py', 'three.py')
    create_target('common/c', 'c', 'four.py')

  def test_all(self):
    self.assert_console_output(
      'common/a/one.py common/a/BUILD:a',
      'common/b/two.py common/b/BUILD:b',
      'common/b/three.py common/b/BUILD:b',
      'common/c/four.py common/c/BUILD:c',
    )

  def test_one(self):
    self.assert_console_output(
      'common/b/two.py common/b/BUILD:b',
      'common/b/three.py common/b/BUILD:b',
      targets=[self.target('common/b')]
    )

  def test_dup(self):
    self.assert_console_output(
      'common/a/one.py common/a/BUILD:a',
      'common/c/four.py common/c/BUILD:c',
      targets=[self.target('common/a'), self.target('common/c'), self.target('common/a')]
    )

