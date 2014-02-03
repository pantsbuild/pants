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

from twitter.pants.tasks.filter import Filter

from . import ConsoleTaskTest


class BaseFilterTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Filter


class FilterEmptyTargetsTest(BaseFilterTest):
  def test_no_filters(self):
    self.assert_console_output()

  def test_type(self):
    self.assert_console_output(args=['--test-type=page'])
    self.assert_console_output(args=['--test-type=-java_library'])

  def test_regex(self):
    self.assert_console_output(args=['--test-regex=^common'])
    self.assert_console_output(args=['--test-regex=-^common'])


class FilterTest(BaseFilterTest):
  @classmethod
  def setUpClass(cls):
    super(FilterTest, cls).setUpClass()

    def create_target(path, name, *deps):
      all_deps = ["pants('%s')" % dep for dep in list(deps)] + ["python_requirement('foo')"]
      cls.create_target(path, dedent('''
          python_library(name='%s',
            dependencies=[%s]
          )
          ''' % (name, ','.join(all_deps))))

    create_target('common/a', 'a')
    create_target('common/b', 'b')
    create_target('common/c', 'c')
    create_target('overlaps', 'one', 'common/a', 'common/b')
    create_target('overlaps', 'two', 'common/a', 'common/c')
    create_target('overlaps', 'three', 'common/a', 'overlaps:one')

  def test_roots(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      targets=self.targets('common/::'),
      extra_targets=self.targets('overlaps/::')
    )

  def test_nodups(self):
    targets = [self.target('common/b')] * 2
    self.assertEqual(2, len(targets))
    self.assert_console_output(
      'common/b/BUILD:b',
      targets=targets
    )

  def test_no_filters(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      'overlaps/BUILD:foo',
      targets=self.targets('::')
    )

  def test_filter_type(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/b/BUILD:b',
      'common/c/BUILD:c',
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      args=['--test-type=python_library'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a/BUILD:foo',
      'common/b/BUILD:foo',
      'common/c/BUILD:foo',
      'overlaps/BUILD:foo',
      args=['--test-type=-python_library'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      'overlaps/BUILD:foo',
      args=['--test-type=PythonRequirement,twitter.pants.targets.PythonLibrary'],
      targets=self.targets('::')
    )

  def test_filter_target(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'overlaps/BUILD:foo',
      args=['--test-target=common/a,overlaps/:foo'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      args=['--test-target=-common/a/BUILD:a,overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

  def test_filter_ancestor(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'overlaps/BUILD:one',
      'overlaps/BUILD:foo',
      args=['--test-ancestor=overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      args=['--test-ancestor=-overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

  def test_filter_regex(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      args=['--test-regex=^common'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a/BUILD:foo',
      'common/b/BUILD:foo',
      'common/c/BUILD:foo',
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      'overlaps/BUILD:foo',
      args=['--test-regex=+foo,^overlaps'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      args=['--test-regex=-^common,foo$'],
      targets=self.targets('::')
    )
