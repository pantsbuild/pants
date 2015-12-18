# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.option.optionable import Optionable
from pants.subsystem.subsystem import Subsystem


class DummySubsystem(Subsystem):
  options_scope = 'dummy'


class DummyOptions(object):
  def for_scope(self, scope):
    return object()


class DummyOptionable(Optionable):
  options_scope = 'foo'


class UninitializedSubsystem(Subsystem):
  options_scope = 'uninitialized-scope'


class SubsystemTest(unittest.TestCase):
  def setUp(self):
    DummySubsystem._options = DummyOptions()

  def test_global_instance(self):
    # Verify that we get the same instance back every time.
    global_instance = DummySubsystem.global_instance()
    self.assertIs(global_instance, DummySubsystem.global_instance())

  def test_scoped_instance(self):
    # Verify that we get the same instance back every time.
    task = DummyOptionable()
    task_instance = DummySubsystem.scoped_instance(task)
    self.assertIs(task_instance, DummySubsystem.scoped_instance(task))

  def test_invalid_subsystem_class(self):
    class NoScopeSubsystem(Subsystem):
      pass
    NoScopeSubsystem._options = DummyOptions()
    with self.assertRaises(NotImplementedError):
      NoScopeSubsystem.global_instance()

  def test_closure_simple(self):
    self.assertEqual({DummySubsystem}, Subsystem.closure((DummySubsystem,)))

  def test_closure_tree(self):
    class SubsystemB(Subsystem):
      options_scope = 'b'

    class SubsystemA(Subsystem):
      options_scope = 'a'

      @classmethod
      def subsystem_dependencies(cls):
        return (DummySubsystem, SubsystemB)

    self.assertEqual({DummySubsystem, SubsystemA, SubsystemB}, Subsystem.closure((SubsystemA,)))
    self.assertEqual({DummySubsystem, SubsystemA, SubsystemB},
                     Subsystem.closure((SubsystemA, SubsystemB)))
    self.assertEqual({DummySubsystem, SubsystemA, SubsystemB},
                     Subsystem.closure((DummySubsystem, SubsystemA, SubsystemB)))

  def test_closure_graph(self):
    class SubsystemB(Subsystem):
      options_scope = 'b'

      @classmethod
      def subsystem_dependencies(cls):
        return (DummySubsystem,)

    class SubsystemA(Subsystem):
      options_scope = 'a'

      @classmethod
      def subsystem_dependencies(cls):
        return (DummySubsystem, SubsystemB)

    self.assertEqual({DummySubsystem, SubsystemB}, Subsystem.closure((SubsystemB,)))

    self.assertEqual({DummySubsystem, SubsystemA, SubsystemB}, Subsystem.closure((SubsystemA,)))
    self.assertEqual({DummySubsystem, SubsystemA, SubsystemB},
                     Subsystem.closure((SubsystemA, SubsystemB)))
    self.assertEqual({DummySubsystem, SubsystemA, SubsystemB},
                     Subsystem.closure((DummySubsystem, SubsystemA, SubsystemB)))

  def test_closure_cycle(self):
    class SubsystemC(Subsystem):
      options_scope = 'c'

      @classmethod
      def subsystem_dependencies(cls):
        return (SubsystemA,)

    class SubsystemB(Subsystem):
      options_scope = 'b'

      @classmethod
      def subsystem_dependencies(cls):
        return (SubsystemC,)

    class SubsystemA(Subsystem):
      options_scope = 'a'

      @classmethod
      def subsystem_dependencies(cls):
        return (SubsystemB,)

    for root in SubsystemA, SubsystemB, SubsystemC:
      with self.assertRaises(Subsystem.CycleException):
        Subsystem.closure((root,))

  def test_uninitialized_global(self):

    with self.assertRaisesRegexp(Subsystem.UninitializedSubsystemError,
                                 r'UninitializedSubsystem.*uninitialized-scope'):
      UninitializedSubsystem.global_instance()

  def test_uninitialized_scoped_instance(self):
    class UninitializedOptional(Optionable):
      options_scope = 'optional'

    optional = UninitializedOptional()
    with self.assertRaisesRegexp(Subsystem.UninitializedSubsystemError,
                                 r'UninitializedSubsystem.*uninitialized-scope'):
      UninitializedSubsystem.scoped_instance(optional)

  def test_subsystem_dependencies_iter(self):
    class SubsystemB(Subsystem):
      options_scope = 'b'

    class SubsystemA(Subsystem):
      options_scope = 'a'

      @classmethod
      def subsystem_dependencies(cls):
        return (DummySubsystem.scoped(cls), SubsystemB)

    dep_scopes = set(dep.options_scope() for dep in SubsystemA.subsystem_dependencies_iter())
    self.assertEqual({'b', 'dummy.a'}, dep_scopes)
