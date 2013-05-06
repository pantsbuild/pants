# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

from twitter.pants.tasks.dependees import ReverseDepmap

from . import ConsoleTaskTest


class BaseReverseDepmapTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return ReverseDepmap


class ReverseDepmapEmptyTest(BaseReverseDepmapTest):
  def test(self):
    self.assert_console_output(targets=[])


class ReverseDepmapTest(BaseReverseDepmapTest):
  @classmethod
  def setUpClass(cls):
    super(ReverseDepmapTest, cls).setUpClass()

    def create_target(path, name, alias=False, deps=()):
      cls.create_target(path, dedent('''
          %(type)s(name='%(name)s',
            dependencies=[%(deps)s]
          )
          ''' % dict(
        type='dependencies' if alias else 'python_library',
        name=name,
        deps=','.join("pants('%s')" % dep for dep in list(deps)))
      ))

    create_target('common/a', 'a')
    create_target('common/b', 'b')
    create_target('common/c', 'c')
    create_target('common/d', 'd')
    create_target('overlaps', 'one', deps=['common/a', 'common/b'])
    create_target('overlaps', 'two', deps=['common/a', 'common/c'])
    create_target('overlaps', 'three', deps=['common/a', 'overlaps:one'])
    create_target('overlaps', 'four', alias=True, deps=['common/b'])
    create_target('overlaps', 'five', deps=['overlaps:four'])

  def test_roots(self):
    self.assert_console_output(
      'overlaps/BUILD:two',
      targets=[self.target('common/c')],
      extra_targets=[self.target('common/a')]
    )

  def test_normal(self):
    self.assert_console_output(
      'overlaps/BUILD:two',
      targets=[self.target('common/c')]
    )

  def test_closed(self):
    self.assert_console_output(
      'overlaps/BUILD:two',
      'common/c/BUILD:c',
      args=['--test-closed'],
      targets=[self.target('common/c')]
    )

  def test_transitive(self):
    self.assert_console_output(
      'overlaps/BUILD:one',
      'overlaps/BUILD:three',
      'overlaps/BUILD:four',
      'overlaps/BUILD:five',
      args=['--test-transitive'],
      targets=[self.target('common/b')]
    )

  def test_nodups_dependees(self):
    self.assert_console_output(
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      targets=[
        self.target('common/a'),
        self.target('overlaps:one')
      ],
    )

  def test_nodups_roots(self):
    targets = [self.target('common/c')] * 2
    self.assertEqual(2, len(targets))
    self.assert_console_output(
      'overlaps/BUILD:two',
      'common/c/BUILD:c',
      args=['--test-closed'],
      targets=targets
    )

  def test_aliasing(self):
    self.assert_console_output(
      'overlaps/BUILD:five',
      targets=[self.target('overlaps:four')]
    )
