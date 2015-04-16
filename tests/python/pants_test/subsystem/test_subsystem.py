# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.subsystem.subsystem import Subsystem


class DummySubsystem(Subsystem):
  @classmethod
  def scope_qualifier(cls):
    return 'dummy'


class DummyOptions(object):
  def for_scope(self, scope):
    return object()


class DummyTask(object):
  options_scope = 'foo'


class SubsystemTest(unittest.TestCase):
  def setUp(self):
    DummySubsystem._options = DummyOptions()

  def test_qualify_scope(self):
    self.assertEquals('dummy', DummySubsystem.qualify_scope(''))
    self.assertEquals('foo.dummy', DummySubsystem.qualify_scope('foo'))
    self.assertEquals('foo.bar.dummy', DummySubsystem.qualify_scope('foo.bar'))

  def test_global_instance(self):
    # Verify that we get the same instance back every time.
    global_instance = DummySubsystem.global_instance()
    self.assertIs(global_instance, DummySubsystem.global_instance())

  def test_instance_for_task(self):
    # Verify that we get the same instance back every time.
    task = DummyTask()
    task_instance = DummySubsystem.instance_for_task(task)
    self.assertIs(task_instance, DummySubsystem.instance_for_task(task))
