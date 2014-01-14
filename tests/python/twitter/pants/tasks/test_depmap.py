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

from twitter.pants.tasks.depmap import Depmap
from twitter.pants.tasks import TaskError

from . import ConsoleTaskTest


class BaseDepmapTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Depmap


class DepmapTest(BaseDepmapTest):
  @classmethod
  def setUpClass(cls):
    super(DepmapTest, cls).setUpClass()

    def create_target(path, name, type, deps=(), **kwargs):
      cls.create_target(path, dedent('''
          %(type)s(name='%(name)s',
            dependencies=[%(deps)s],
            %(extra)s
          )
          ''' % dict(
        type=type,
        name=name,
        deps=','.join("pants('%s')" % dep for dep in list(deps)),
        extra=('' if not kwargs else ', '.join('%s=%r' % (k, v) for k, v in kwargs.items()))
      )))

    def create_jvm_app(path, name, type, binary, deps=()):
      cls.create_target(path, dedent('''
          %(type)s(name='%(name)s',
            binary=pants('%(binary)s'),
            bundles=%(deps)s
          )
          ''' % dict(
        type=type,
        name=name,
        binary=binary,
        deps=deps)
      ))

    create_target('common/a', 'a', 'dependencies')
    create_target('common/b', 'b', 'jar_library')
    create_target('common/c', 'c', 'scala_library')
    create_target('common/d', 'd', 'python_library')
    create_target('common/e', 'e', 'python_binary', entry_point='foo:main')
    create_target('common/f', 'f', 'jvm_binary')
    create_target('common/g', 'g', 'jvm_binary', deps=['common/f:f'])
    create_jvm_app('common/h', 'h', 'jvm_app', 'common/f:f', "bundle().add('common.f')")
    create_jvm_app('common/i', 'i', 'jvm_app', 'common/g:g', "bundle().add('common.g')")
    create_target('overlaps', 'one', 'jvm_binary', deps=['common/h', 'common/i'])
    create_target('overlaps', 'two', 'scala_library', deps=['overlaps:one'])

  def test_empty(self):
    self.assert_console_raises(
      TaskError,
      targets=[self.target('common/a')]
    )

  def test_jar_library(self):
    self.assert_console_raises(
      TaskError,
      targets=[self.target('common/b')],
    )

  def test_scala_library(self):
    self.assert_console_output(
      'internal-common.c.c',
      targets=[self.target('common/c')]
    )

  def test_python_library(self):
    self.assert_console_raises(
      TaskError,
      targets=[self.target('common/d')]
    )

  def test_python_binary(self):
    self.assert_console_raises(
      TaskError,
      targets=[self.target('common/e')]
    )

  def test_jvm_binary1(self):
    self.assert_console_output(
      'internal-common.f.f',
      targets=[self.target('common/f')]
    )

  def test_jvm_binary2(self):
    self.assert_console_output(
      'internal-common.g.g',
      '  internal-common.f.f',
      targets=[self.target('common/g')]
    )

  def test_jvm_app1(self):
    self.assert_console_output(
      'internal-common.h.h',
      '  internal-common.f.f',
      targets=[self.target('common/h')]
    )

  def test_jvm_app2(self):
    self.assert_console_output(
      'internal-common.i.i',
      '  internal-common.g.g',
      '    internal-common.f.f',
      targets=[self.target('common/i')]
    )

  def test_overlaps_one(self):
    self.assert_console_output(
      'internal-overlaps.one',
      '  internal-common.h.h',
      '    internal-common.f.f',
      '  internal-common.i.i',
      '    internal-common.g.g',
      '      *internal-common.f.f',
      targets=[self.target('overlaps:one')]
    )

  def test_overlaps_two(self):
    self.assert_console_output(
      'internal-overlaps.two',
      '  internal-overlaps.one',
      '    internal-common.h.h',
      '      internal-common.f.f',
      '    internal-common.i.i',
      '      internal-common.g.g',
      '        *internal-common.f.f',
      targets=[self.target('overlaps:two')]
    )

  def test_overlaps_two_minimal(self):
    self.assert_console_output(
      'internal-overlaps.two',
      '  internal-overlaps.one',
      '    internal-common.h.h',
      '      internal-common.f.f',
      '    internal-common.i.i',
      '      internal-common.g.g',
      targets=[self.target('overlaps:two')],
      args=['--test-minimal']
    )
