# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import itertools

from pants.backend.core.tasks.check_exclusives import ExclusivesMapping
from pants.backend.core.tasks.group_task import GroupMember, GroupIterator, GroupTask
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.python.targets.python_library import PythonLibrary

from pants_test.base_test import BaseTest


class GroupIteratorTestBase(BaseTest):
  def group_member(self, name, predicate):
    class TestMember(GroupMember):
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
    context = self.context(target_roots=targets)

    def workdir():
      return None

    return list(GroupIterator(list(targets),
                              [self.red(context, workdir()),
                               self.green(context, workdir()),
                               self.blue(context, workdir())]))


class GroupIteratorSingleTest(GroupIteratorTestBase):
  def test(self):
    colorless = self.make_target('root:colorless', JavaLibrary)
    a_red = self.make_target('root:a_red', JavaLibrary, dependencies=[colorless])
    b_red = self.make_target('root:b_red', JavaLibrary, dependencies=[a_red])
    c_red = self.make_target('root:c_red', JavaLibrary, dependencies=[a_red, colorless])
    d_red = self.make_target('root:d_red', JavaLibrary, dependencies=[b_red, c_red])

    chunks = self.iterate(d_red)
    self.assertEqual(1, len(chunks))

    group_member, targets = chunks[0]
    self.assertEqual(self.red, type(group_member))
    self.assertEqual(set([a_red, b_red, c_red, d_red]), set(targets))


class GroupIteratorMultipleTest(GroupIteratorTestBase):
  def test(self):
    colorless = self.make_target('root:colorless', JavaLibrary)
    a_red = self.make_target('root:a_red', JavaLibrary, dependencies=[colorless])
    a_blue = self.make_target('root:a_blue', JavaLibrary, dependencies=[a_red])
    a_green = self.make_target('root:a_green', JavaLibrary, dependencies=[a_blue, colorless])
    b_red = self.make_target('root:b_red', JavaLibrary, dependencies=[a_blue])
    c_red = self.make_target('root:c_red', JavaLibrary, dependencies=[b_red])

    chunks = self.iterate(c_red, a_green)
    self.assertEqual(4, len(chunks))

    group_member, targets = chunks[0]
    self.assertEqual(self.red, type(group_member))
    self.assertEqual(set([a_red]), set(targets))

    group_member, targets = chunks[1]
    self.assertEqual(self.blue, type(group_member))
    self.assertEqual(set([a_blue]), set(targets))

    group_member, targets = chunks[2]
    self.assertEqual(self.green, type(group_member))
    self.assertEqual(set([a_green]), set(targets))

    group_member, targets = chunks[3]
    self.assertEqual(self.red, type(group_member))
    self.assertEqual(set([b_red, c_red]), set(targets))


class GroupTaskTest(BaseTest):
  def setUp(self):
    super(GroupTaskTest, self).setUp()

    self.a = self.make_target('src/java:a', JavaLibrary)
    self.b = self.make_target('src/scala:b', ScalaLibrary, dependencies=[self.a])
    self.c = self.make_target('src/java:c', JavaLibrary, dependencies=[self.b])
    self.d = self.make_target('src/scala:d', ScalaLibrary, dependencies=[self.c])
    self.e = self.make_target('src/java:e', JavaLibrary, dependencies=[self.d])
    f = self.make_target('src/python:f', PythonLibrary)

    self._context = self.context(target_roots=[self.e, f])

    exclusives_mapping = ExclusivesMapping(self._context)
    exclusives_mapping._populate_target_maps(self._context.targets())
    self._context.products.safe_create_data('exclusives_groups', lambda: exclusives_mapping)

    self.recorded_actions = []

  def construct_action(self, tag):
    return 'construct', tag, self.context

  def prepare_action(self, tag):
    return 'prepare', tag, self.context

  def prepare_execute_action(self, tag, chunks):
    return 'prepare_execute', tag, chunks

  def execute_chunk_action(self, tag, targets):
    return 'execute_chunk', tag, targets

  def post_execute_action(self, tag):
    return 'post_execute', tag, self.context

  def group_member(self, name, selector):
    class RecordingGroupMember(GroupMember):
      def __init__(me, context, workdir):
        super(RecordingGroupMember, me).__init__(context, workdir)
        self.recorded_actions.append(self.construct_action(name))

      def prepare(me):
        self.recorded_actions.append(self.prepare_action(name))

      def select(me, target):
        return selector(target)

      def prepare_execute(me, chunks):
        self.recorded_actions.append(self.prepare_execute_action(name, chunks))

      def execute_chunk(me, targets):
        self.recorded_actions.append(self.execute_chunk_action(name, targets))

      def post_execute(me):
        self.recorded_actions.append(self.post_execute_action(name))

    return RecordingGroupMember

  def test_groups(self):
    group_task = GroupTask.named('jvm-compile', 'classes')
    group_task.add_member(self.group_member('javac', lambda t: t.is_java))
    group_task.add_member(self.group_member('scalac', lambda t: t.is_scala))

    task = group_task(self._context, workdir='/not/real')
    task.prepare()
    task.execute()

    # These items will be executed by GroupTask in order.
    expected_prepare_actions = [self.construct_action('javac'),
        self.prepare_action('javac'),
        self.construct_action('scalac'),
        self.prepare_action('scalac')]

    # The ordering of the execution of these items isn't guaranteed:
    #
    #  https://groups.google.com/d/msg/pants-devel/Rer9_ytsyf8/gi8zokWNexYJ
    #
    # So we store these separately, to do a special comparison later on.
    expected_prepare_execute_actions = [
        self.prepare_execute_action('javac', [[self.a], [self.c], [self.e]]),
        self.prepare_execute_action('scalac', [[self.b], [self.d]])
    ]

    expected_execute_actions = [self.execute_chunk_action('javac', targets=[self.a]),
        self.execute_chunk_action('scalac', targets=[self.b]),
        self.execute_chunk_action('javac', targets=[self.c]),
        self.execute_chunk_action('scalac', targets=[self.d]),
        self.execute_chunk_action('javac', targets=[self.e]),
        self.post_execute_action('javac'),
        self.post_execute_action('scalac')]

    recorded_iter = iter(self.recorded_actions)

    # Now, we compare the list of actions executed, with what we expected, in chunks. We first peel
    # off the first 4 items from what was executed, and compare with the "expected_prepare_actions"
    # list.
    actual_prepare_actions = list(itertools.islice(recorded_iter, len(expected_prepare_actions)))
    self.assertEqual(expected_prepare_actions, actual_prepare_actions)

    # Next, we slice off the next two elements from the array, store them separately, sort both the
    # recorded elements and the expected elements, and compare.
    actual_prepare_execute_actions = list(itertools.islice(recorded_iter, len(expected_prepare_execute_actions)))
    self.assertEqual(sorted(expected_prepare_execute_actions), sorted(actual_prepare_execute_actions))

    # Finally, compare the remaining items.
    self.assertEqual(expected_execute_actions, list(recorded_iter))
