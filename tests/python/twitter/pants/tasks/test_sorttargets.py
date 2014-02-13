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

from textwrap import dedent

from twitter.pants.tasks.sorttargets import SortTargets

from . import ConsoleTaskTest


class BaseSortTargetsTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return SortTargets


class SortTargetsEmptyTest(BaseSortTargetsTest):
  def test(self):
    self.assert_console_output(targets=[])


class SortTargetsTest(BaseSortTargetsTest):

  @classmethod
  def setUpClass(cls):
    super(SortTargetsTest, cls).setUpClass()

    def create_target(path, name, *deps):
      all_deps = ["pants('%s')" % dep for dep in list(deps)]
      cls.create_target(path, dedent('''
          python_library(name='%s',
            dependencies=[%s]
          )
          ''' % (name, ','.join(all_deps))))

    create_target('common/a', 'a')
    create_target('common/b', 'b', 'common/a')
    create_target('common/c', 'c', 'common/a', 'common/b')

  def test_sort(self):
    targets = [self.target('common/a'), self.target('common/c'), self.target('common/b')]
    self.assertEqual(['common/a/BUILD:a', 'common/b/BUILD:b', 'common/c/BUILD:c'],
                     list(self.execute_console_task(targets=targets)))

  def test_sort_reverse(self):
    targets = [self.target('common/c'), self.target('common/a'), self.target('common/b')]
    self.assertEqual(['common/c/BUILD:c', 'common/b/BUILD:b', 'common/a/BUILD:a'],
                     list(self.execute_console_task(targets=targets, args=['--test-reverse'])))
