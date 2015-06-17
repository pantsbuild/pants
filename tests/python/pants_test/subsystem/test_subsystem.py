# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.subsystem.subsystem import Subsystem


class DummySubsystem(Subsystem):
  options_scope = 'dummy'


class DummyOptions(object):
  def for_scope(self, scope):
    return object()


class DummyTask(object):
  options_scope = 'foo'


class SubsystemTest(unittest.TestCase):
  def setUp(self):
    DummySubsystem._options = DummyOptions()

  def test_global_instance(self):
    # Verify that we get the same instance back every time.
    global_instance = DummySubsystem.global_instance()
    self.assertIs(global_instance, DummySubsystem.global_instance())

  def test_instance_for_task(self):
    # Verify that we get the same instance back every time.
    task = DummyTask()
    task_instance = DummySubsystem.instance_for_task(task)
    self.assertIs(task_instance, DummySubsystem.instance_for_task(task))

  def test_invalid_subsystem_class(self):
    class NoScopeSubsystem(Subsystem):
      pass
    NoScopeSubsystem._options = DummyOptions()
    with self.assertRaises(NotImplementedError):
      NoScopeSubsystem.global_instance()
