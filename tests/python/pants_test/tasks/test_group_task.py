# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import uuid

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.tasks.group_task import GroupIterator, GroupMember, GroupTask
from pants.build_graph.target import Target
from pants.engine.round_manager import RoundManager
from pants_test.base_test import BaseTest


class GroupIteratorTestBase(BaseTest):
  def group_member(self, name, predicate):
    class TestMember(GroupMember):
      options_scope = 'test_member'

      @classmethod
      def name(cls):
        return name

      def select(self, target):
        return predicate(target)

      def execute_chunk(self, targets):
        pass

    return TestMember

  def setUp(self):
    super(GroupIteratorTestBase, self).setUp()

    self.red = self.group_member('red', lambda tgt: 'red' in tgt.name)
    self.green = self.group_member('green', lambda tgt: 'green' in tgt.name)
    self.blue = self.group_member('blue', lambda tgt: 'blue' in tgt.name)

  def iterate(self, *targets):
    context = self.context(target_roots=targets,
                           for_task_types=[self.red, self.green, self.blue])

    def workdir():
      return None

    return list(GroupIterator(list(targets),
                              [self.red(context, workdir()),
                               self.green(context, workdir()),
                               self.blue(context, workdir())]))


class GroupIteratorSingleTest(GroupIteratorTestBase):
  def test(self):
    colorless = self.make_target('root:colorless', Target)
    a_red = self.make_target('root:a_red', Target, dependencies=[colorless])
    b_red = self.make_target('root:b_red', Target, dependencies=[a_red])
    c_red = self.make_target('root:c_red', Target, dependencies=[a_red, colorless])
    d_red = self.make_target('root:d_red', Target, dependencies=[b_red, c_red])

    chunks = self.iterate(d_red)
    self.assertEqual(1, len(chunks))

    group_member, targets = chunks[0]
    self.assertEqual(self.red, type(group_member))
    self.assertEqual({a_red, b_red, c_red, d_red}, set(targets))


class GroupIteratorMultipleTest(GroupIteratorTestBase):
  def test(self):
    colorless = self.make_target('root:colorless', Target)
    a_red = self.make_target('root:a_red', Target, dependencies=[colorless])
    a_blue = self.make_target('root:a_blue', Target, dependencies=[a_red])
    a_green = self.make_target('root:a_green', Target, dependencies=[a_blue, colorless])
    b_red = self.make_target('root:b_red', Target, dependencies=[a_blue])
    c_red = self.make_target('root:c_red', Target, dependencies=[b_red])

    chunks = self.iterate(c_red, a_green)
    self.assertEqual(4, len(chunks))

    group_members, target_lists = zip(*chunks)
    group_member_types = [type(group_member) for group_member in group_members]
    target_sets = [set(target_list) for target_list in target_lists]

    # There are two possible topological orders, both correct.
    first_possible_group_member_types = [self.red, self.blue, self.red, self.green]
    first_possible_target_sets = [{a_red}, {a_blue}, {b_red, c_red}, {a_green}]
    second_possible_group_member_types = [self.red, self.blue, self.green, self.red]
    second_possible_target_sets = [{a_red}, {a_blue}, {a_green}, {b_red, c_red}]

    self.assertIn(
      (group_member_types, target_sets),
      [(first_possible_group_member_types, first_possible_target_sets),
       (second_possible_group_member_types, second_possible_target_sets)])


class BaseGroupTaskTest(BaseTest):

  class JavaLibrary(Target):
    pass

  class PythonLibrary(Target):
    pass

  class ScalaLibrary(Target):
    pass

  def create_targets(self):
    """Creates targets and returns the target roots for this GroupTask"""

  def setUp(self):
    super(BaseGroupTaskTest, self).setUp()
    self.set_options_for_scope('test.RecordingGroupMember', level='info', colors='False')

    self.maxDiff = None

    self.recorded_actions = []
    # NB: GroupTask has a cache of tasks by name... use a distinct name
    self.group_task = GroupTask.named('jvm-compile-%s' % uuid.uuid4().hex,
                                      ['classes_by_target', 'classes_by_source'],
                                      ['test'])

    javac = self.group_member(name='javac', selector=lambda t: isinstance(t, self.JavaLibrary))
    self.group_task.add_member(javac)

    scalac = self.group_member(name='scalac', selector=lambda t: isinstance(t, self.ScalaLibrary))
    self.group_task.add_member(scalac)

    self._context = self.context(target_roots=self.create_targets(),
                                 for_task_types=[self.group_task])
    self.populate_compile_classpath(self._context)
    self.group_task._prepare(self.options, round_manager=RoundManager(self._context))


    self.task = self.group_task(self._context, workdir='/not/real')
    self.task.execute()

  def assertUnorderedPrefixEqual(self, expected, actual_iter):
    """The ordering of the execution of some of these items isn't guaranteed.

    https://groups.google.com/d/msg/pants-devel/Rer9_ytsyf8/gi8zokWNexYJ
    """
    actual = list(itertools.islice(actual_iter, len(expected)))
    self.assertEqual(sorted(expected), sorted(actual))

  def assertPrefixEqual(self, expected, actual_iter):
    self.assertEqual(expected, list(itertools.islice(actual_iter, len(expected))))

  def prepare_action(self, tag):
    return 'prepare', tag, self._context

  def construct_action(self, tag):
    return 'construct', tag, self._context

  def prepare_execute_action(self, tag, chunks):
    return 'prepare_execute', tag, chunks

  def finalize_execute_action(self, tag, chunks):
    return 'finalize_execute', tag, chunks

  def pre_execute_action(self, tag):
    return 'pre_execute', tag

  def execute_chunk_action(self, tag, targets):
    return 'execute_chunk', tag, targets

  def post_execute_action(self, tag):
    return 'post_execute', tag, self._context

  def group_member(self, name, selector):
    class RecordingGroupMember(GroupMember):
      @classmethod
      def prepare(cls, options, round_manager):
        self.recorded_actions.append(self.prepare_action(name))

      def __init__(me, *args, **kwargs):
        super(RecordingGroupMember, me).__init__(*args, **kwargs)
        self.recorded_actions.append(self.construct_action(name))

      def select(me, target):
        return selector(target)

      def prepare_execute(me, chunks):
        self.recorded_actions.append(self.prepare_execute_action(name, chunks))

      def finalize_execute(me, chunks):
        self.recorded_actions.append(self.finalize_execute_action(name, chunks))

      def pre_execute(me):
        self.recorded_actions.append(self.pre_execute_action(name))

      def execute_chunk(me, targets):
        self.recorded_actions.append(self.execute_chunk_action(name, targets))

      def post_execute(me):
        self.recorded_actions.append(self.post_execute_action(name))

    return RecordingGroupMember


class GroupTaskTest(BaseGroupTaskTest):

  def create_targets(self):
    self.a = self.make_target('src/java:a', self.JavaLibrary)
    self.b = self.make_target('src/scala:b', self.ScalaLibrary, dependencies=[self.a])
    self.c = self.make_target('src/java:c', self.JavaLibrary, dependencies=[self.b])
    self.d = self.make_target('src/scala:d', self.ScalaLibrary, dependencies=[self.c])
    self.e = self.make_target('src/java:e', self.JavaLibrary, dependencies=[self.d])
    f = self.make_target('src/python:f', self.PythonLibrary)
    return [self.e, f]

  def test_groups(self):
    """Compare the list of actions executed, with what we expected, in chunks."""

    recorded_iter = iter(self.recorded_actions)

    self.assertPrefixEqual([
        self.prepare_action('javac'),
        self.prepare_action('scalac')], recorded_iter)

    self.assertUnorderedPrefixEqual([
        self.construct_action('javac'),
        self.construct_action('scalac'),
        self.pre_execute_action('javac'),
        self.pre_execute_action('scalac')],
      recorded_iter)

    self.assertUnorderedPrefixEqual([
        self.prepare_execute_action('javac', [[self.a], [self.c], [self.e]]),
        self.prepare_execute_action('scalac', [[self.b], [self.d]])],
      recorded_iter)

    # Compare the execute items in linear order
    self.assertPrefixEqual([
        self.execute_chunk_action('javac', targets=[self.a]),
        self.execute_chunk_action('scalac', targets=[self.b]),
        self.execute_chunk_action('javac', targets=[self.c]),
        self.execute_chunk_action('scalac', targets=[self.d]),
        self.execute_chunk_action('javac', targets=[self.e])],
      recorded_iter)

    self.assertUnorderedPrefixEqual([
        self.finalize_execute_action('javac', [[self.a], [self.c], [self.e]]),
        self.finalize_execute_action('scalac', [[self.b], [self.d]])],
      recorded_iter)

    self.assertUnorderedPrefixEqual([
        self.post_execute_action('javac'),
        self.post_execute_action('scalac')],
      recorded_iter)

    # Ensure no more entries
    self.assertEqual([], list(recorded_iter))


class EmptyGroupTaskTest(BaseGroupTaskTest):
  def create_targets(self):
    self.a = self.make_target('src/java:a', Target)
    self.b = self.make_target('src/scala:b', Target, dependencies=[self.a])
    return [self.a]

  def test_groups(self):
    # These items will be executed by GroupTask in order.
    expected_prepare_actions = [
        self.prepare_action('javac'),
        self.prepare_action('scalac')]

    # The ordering of the execution of these items isn't guaranteed.
    expected_prepare_execute_actions = [
        self.construct_action('javac'),
        self.construct_action('scalac'),
        self.pre_execute_action('javac'),
        self.pre_execute_action('scalac'),
        self.post_execute_action('javac'),
        self.post_execute_action('scalac')]

    recorded_iter = iter(self.recorded_actions)

    actual_prepare_actions = list(itertools.islice(recorded_iter, len(expected_prepare_actions)))
    self.assertEqual(expected_prepare_actions, actual_prepare_actions)

    self.assertEqual(sorted(expected_prepare_execute_actions), sorted(list(recorded_iter)))


class TransitiveGroupTaskTest(BaseGroupTaskTest):
  def create_targets(self):
    self.a = self.make_target('src/scala:a', self.ScalaLibrary)
    self.b = self.make_target('src/deps:b', Dependencies, dependencies=[self.a])
    self.c = self.make_target('src/java:c', self.JavaLibrary, dependencies=[self.b])
    self.d = self.make_target('src/scala:d', self.ScalaLibrary, dependencies=[self.c])
    return [self.d]

  def test_transitive_groups(self):
    recorded_iter = iter(self.recorded_actions)

    # expecting prepare/construct for java/scalac, then pre-execute/prepare_execute for
    # javac/scalac: ignore 8
    list(itertools.islice(recorded_iter, 8))

    # Compare the execution in order.
    self.assertPrefixEqual([
        self.execute_chunk_action('scalac', targets=[self.a]),
        self.execute_chunk_action('javac', targets=[self.c]),
        self.execute_chunk_action('scalac', targets=[self.d])],
      recorded_iter)

    # And finalizing actions in any order
    self.assertUnorderedPrefixEqual([
        self.finalize_execute_action('javac', [[self.c]]),
        self.finalize_execute_action('scalac', [[self.a], [self.d]]),
        self.post_execute_action('javac'),
        self.post_execute_action('scalac')],
      recorded_iter)
