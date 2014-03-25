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

import pytest
import unittest

from textwrap import dedent

from twitter.pants.engine.group_engine import GroupEngine, GroupIterator, GroupMember
from twitter.pants.goal import Goal, Group
from twitter.pants.tasks import Task
from twitter.pants.tasks.check_exclusives import ExclusivesMapping

from ..base.context_utils import create_context
from ..base_build_root_test import BaseBuildRootTest
from .base_engine_test import EngineTestBase


class GroupMemberTest(unittest.TestCase):
  def test_from_goal_valid(self):
    def predicate(tgt):
      return tgt == 42

    goal = Goal('fred', action=lambda: None, group=Group('heathers', predicate))
    self.assertEqual(GroupMember('heathers', 'fred', predicate), GroupMember.from_goal(goal))

  def test_from_goal_invalid(self):
    with pytest.raises(ValueError):
      GroupMember.from_goal(Goal('fred', action=lambda: None))


class JvmTargetTest(BaseBuildRootTest):
  @classmethod
  def java_library(cls, path, name, deps=None):
    cls._library(path, 'java_library', name, deps)

  @classmethod
  def python_library(cls, path, name, deps=None):
    cls._library(path, 'python_library', name, deps)

  @classmethod
  def scala_library(cls, path, name, deps=None):
    cls._library(path, 'scala_library', name, deps)

  @classmethod
  def _library(cls, path, target_type, name, deps=None):
    cls.create_target(path, dedent('''
      %(target_type)s(name='%(name)s',
        dependencies=[%(deps)s],
        sources=[],
      )
    ''' % dict(target_type=target_type,
               name=name,
               deps=','.join('pants("%s")' % d for d in (deps or [])))))

  @classmethod
  def targets(cls, *addresses):
    return map(cls.target, addresses)


class GroupIteratorTestBase(JvmTargetTest):
  def setUp(self):
    super(GroupIteratorTestBase, self).setUp()

    self.red = GroupMember('colors', 'red', lambda tgt: 'red' in tgt.name)
    self.green = GroupMember('colors', 'green', lambda tgt: 'green' in tgt.name)
    self.blue = GroupMember('colors', 'blue', lambda tgt: 'blue' in tgt.name)

  def iterate(self, *addresses):
    return list(GroupIterator(self.targets(*addresses), [self.red, self.green, self.blue]))


class GroupIteratorSingleTest(GroupIteratorTestBase):
  def test(self):
    self.java_library('root', 'colorless', deps=[])
    self.java_library('root', 'a_red', deps=['root:colorless'])
    self.java_library('root', 'b_red', deps=['root:a_red'])
    self.java_library('root', 'c_red', deps=['root:a_red', 'root:colorless'])
    self.java_library('root', 'd_red', deps=['root:b_red', 'root:c_red'])

    chunks = self.iterate('root:d_red')
    self.assertEqual(1, len(chunks))

    group_member, targets = chunks[0]
    self.assertEqual(self.red, group_member)
    self.assertEqual(set(self.targets('root:d_red', 'root:b_red', 'root:c_red', 'root:a_red')),
                     set(targets))


class GroupIteratorMultipleTest(GroupIteratorTestBase):
  def test(self):
    self.java_library('root', 'colorless', deps=[])
    self.java_library('root', 'a_red', deps=['root:colorless'])
    self.java_library('root', 'a_blue', deps=['root:a_red'])
    self.java_library('root', 'a_green', deps=['root:a_blue', 'root:colorless'])
    self.java_library('root', 'b_red', deps=['root:a_blue'])
    self.java_library('root', 'c_red', deps=['root:b_red'])

    chunks = self.iterate('root:c_red', 'root:a_green')
    self.assertEqual(4, len(chunks))

    group_member, targets = chunks[0]
    self.assertEqual(self.red, group_member)
    self.assertEqual(set(self.targets('root:a_red')), set(targets))

    group_member, targets = chunks[1]
    self.assertEqual(self.blue, group_member)
    self.assertEqual(set(self.targets('root:a_blue')), set(targets))

    group_member, targets = chunks[2]
    self.assertEqual(self.green, group_member)
    self.assertEqual(set(self.targets('root:a_green')), set(targets))

    group_member, targets = chunks[3]
    self.assertEqual(self.red, group_member)
    self.assertEqual(set(self.targets('root:b_red', 'root:c_red')), set(targets))


class GroupIteratorTargetsTest(GroupIteratorTestBase):
  """Test that GroupIterator raises an exception when given non-internal targets."""

  def test_internal_targets(self):
    self.java_library('root', 'colorless', deps=[])
    self.iterate('root:colorless')

  def test_non_internal_targets(self):
    self.python_library('root2', 'colorless', deps=[])
    with pytest.raises(ValueError):
      self.iterate('root2:colorless')


class GroupEngineTest(EngineTestBase, JvmTargetTest):
  @classmethod
  def setUpClass(cls):
    super(GroupEngineTest, cls).setUpClass()

    cls.java_library('src/java', 'a')
    cls.scala_library('src/scala', 'b', deps=['src/java:a'])
    cls.java_library('src/java', 'c', deps=['src/scala:b'])
    cls.scala_library('src/scala', 'd', deps=['src/java:c'])
    cls.java_library('src/java', 'e', deps=['src/scala:d'])
    cls.python_library('src/python', 'f')

  def setUp(self):
    super(GroupEngineTest, self).setUp()

    self.context = create_context(options=dict(explain=False),
                                  target_roots=self.targets('src/java:e', 'src/python:f'))
    self.assertTrue(self.context.is_unlocked())

    # TODO(John Sirois): disentangle GroupEngine from relying upon the CheckExclusives task being
    # run.  It should either arrange this directly or else the requirement should be in a different
    # layer.
    exclusives_mapping = ExclusivesMapping(self.context)
    exclusives_mapping._populate_target_maps(self.context.targets())
    self.context.products.safe_create_data('exclusives_groups', lambda: exclusives_mapping)

    self.engine = GroupEngine(print_timing=False)
    self.recorded_actions = []

  def tearDown(self):
    self.assertTrue(self.context.is_unlocked())

  def construct_action(self, tag):
    return 'construct', tag, self.context

  def execute_action(self, tag, targets=None):
    return 'execute', tag, (targets or self.context.targets())

  def record(self, tag):
    class RecordingTask(Task):
      def __init__(me, context):
        super(RecordingTask, me).__init__(context)
        self.recorded_actions.append(self.construct_action(tag))

      def execute(me, targets):
        self.recorded_actions.append(self.execute_action(tag, targets=targets))

    return RecordingTask

  def install_goal(self, name, group=None, dependencies=None, phase=None):
    return self.installed_goal(name,
                               action=self.record(name),
                               group=group,
                               dependencies=dependencies,
                               phase=phase)

  def test_no_groups(self):
    self.install_goal('resolve')
    self.install_goal('javac', dependencies=['resolve'], phase='compile')
    self.install_goal('checkstyle', phase='compile')
    self.install_goal('resources')
    self.install_goal('test', dependencies=['compile', 'resources'])

    result = self.engine.execute(self.context, self.as_phases('test'))
    self.assertEqual(0, result)

    expected = [self.construct_action('test'),
                self.construct_action('resources'),
                self.construct_action('checkstyle'),
                self.construct_action('javac'),
                self.construct_action('resolve'),
                self.execute_action('resolve'),
                self.execute_action('javac'),
                self.execute_action('checkstyle'),
                self.execute_action('resources'),
                self.execute_action('test')]
    self.assertEqual(expected, self.recorded_actions)

  def test_groups(self):
    self.install_goal('resolve')
    self.install_goal('javac',
                      group=Group('jvm', lambda t: t.is_java),
                      dependencies=['resolve'],
                      phase='compile')
    self.install_goal('scalac',
                      group=Group('jvm', lambda t: t.is_scala),
                      dependencies=['resolve'],
                      phase='compile')
    self.install_goal('checkstyle', phase='compile')

    result = self.engine.execute(self.context, self.as_phases('compile'))
    self.assertEqual(0, result)

    expected = [self.construct_action('checkstyle'),
                self.construct_action('scalac'),
                self.construct_action('javac'),
                self.construct_action('resolve'),
                self.execute_action('resolve'),
                self.execute_action('javac', targets=self.targets('src/java:a')),
                self.execute_action('scalac', targets=self.targets('src/scala:b')),
                self.execute_action('javac', targets=self.targets('src/java:c')),
                self.execute_action('scalac', targets=self.targets('src/scala:d')),
                self.execute_action('javac', targets=self.targets('src/java:e')),
                self.execute_action('checkstyle')]
    self.assertEqual(expected, self.recorded_actions)

