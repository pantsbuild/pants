# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.backend.core.tasks.group_task import GroupMember, GroupTask
from pants.backend.core.tasks.task import Task
from pants.goal.goal import Goal
from pants.option.scope_hierarchy import ScopeHierarchy
from pants.subsystem.subsystem import Subsystem


class DummySubsystem(Subsystem):
  @classmethod
  def scope_qualifier(cls):
    return 'subsystem'


class DummyTask(Task):
  @classmethod
  def task_subsystems(cls):
    return (DummySubsystem, )


class DummyTaskRegistrar(object):
  def __init__(self, name):
    self.name = name
    self.task_type = DummyTask
    self.serialize = False


class DummyGroupMember1(GroupMember):
  @classmethod
  def name(cls):
    return 'gm1'


class DummyGroupMember2(GroupMember):
  @classmethod
  def name(cls):
    return 'gm2'

  @classmethod
  def task_subsystems(cls):
    return (DummySubsystem, )


class DummyGroupRegistrar(object):
  def __init__(self, name, group_task):
    self.name = name
    self.task_type = group_task
    self.serialize = False


class GoalTest(unittest.TestCase):
  def setUp(self):
    super(GoalTest, self).setUp()
    self.addCleanup(Goal.clear)
    def clean_group_task():
      GroupTask._GROUPS = {}
    self.addCleanup(clean_group_task)

  def test_scope_gathering(self):
    # Test the scope-gathering logic in Goal and GroupTask.
    goal = Goal.by_name('foo')
    goal.install(DummyTaskRegistrar('foo'))  # Same name as goal: foo.foo should be elided to foo.
    goal.install(DummyTaskRegistrar('bar'))
    goal.install(DummyTaskRegistrar('baz'))

    group_task = GroupTask.named('qux', 'product', ['qux'])
    group_task.add_member(DummyGroupMember1)
    group_task.add_member(DummyGroupMember2)
    goal.install(DummyGroupRegistrar('qux', group_task))

    scope_hierarchy = ScopeHierarchy()
    scope_hierarchy.register(DummySubsystem.qualify_scope(''), qualified=True)
    goal.gather_scopes(scope_hierarchy)
    expected = {
      '': None,
      'foo': '',
      'foo.bar': 'foo',
      'foo.bar.subsystem': 'foo.subsystem',
      'foo.baz': 'foo',
      'foo.baz.subsystem': 'foo.subsystem',
      'foo.subsystem': 'subsystem',
      'qux': '',
      'qux.gm1': 'qux',
      'qux.gm2': 'qux',
      'qux.gm2.subsystem': 'qux.subsystem',
      'qux.subsystem': 'subsystem',
      'subsystem': ''
    }
    self.assertItemsEqual(expected.keys(), scope_hierarchy.get_known_scopes())
    self.assertEqual(expected, scope_hierarchy.scope_to_parent)
