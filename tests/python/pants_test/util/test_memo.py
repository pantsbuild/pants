# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.memo import memoized, memoized_classmethod, memoized_property, memoized_staticmethod


class MemoizeTest(unittest.TestCase):
  def test_function_application_positional(self):
    calculations = []

    @memoized
    def multiply(first, second):
      calculations.append((first, second))
      return first * second

    self.assertEqual(6, multiply(2, 3))
    self.assertEqual(6, multiply(3, 2))
    self.assertEqual(6, multiply(2, 3))

    self.assertEquals([(2, 3), (3, 2)], calculations)

  def test_function_application_kwargs(self):
    calculations = []

    @memoized
    def multiply(first, second):
      calculations.append((first, second))
      return first * second

    self.assertEqual(6, multiply(first=2, second=3))
    self.assertEqual(6, multiply(second=3, first=2))
    self.assertEqual(6, multiply(first=2, second=3))

    self.assertEquals([(2, 3)], calculations)

  def test_function_application_mixed(self):
    calculations = []

    @memoized
    def func(*args, **kwargs):
      calculations.append((args, kwargs))
      return args, kwargs

    self.assertEqual((('a',), {'fred': 42, 'jane': True}), func('a', fred=42, jane=True))
    self.assertEqual((('a', 42), {'jane': True}), func('a', 42, jane=True))
    self.assertEqual((('a',), {'fred': 42, 'jane': True}), func('a', jane=True, fred=42))

    self.assertEquals([(('a',), {'fred': 42, 'jane': True}),
                       (('a', 42), {'jane': True})], calculations)

  class Called(object):
    def __init__(self, increment):
      self._calls = 0
      self._increment = increment

    def _called(self):
      self._calls += self._increment
      return self._calls

  def test_instancemethod_application(self):
    class Foo(self.Called):
      @memoized
      def calls(self):
        return self._called()

    foo1 = Foo(1)
    self.assertEqual(1, foo1.calls())
    self.assertEqual(1, foo1.calls())

    foo2 = Foo(2)
    self.assertEqual(2, foo2.calls())
    self.assertEqual(2, foo2.calls())

  def test_descriptor_application_invalid(self):
    with self.assertRaises(ValueError):
      # Can't decorate a descriptor
      class Foo(object):
        @memoized
        @property
        def name(self):
          pass

  def test_descriptor_application_valid(self):
    class Foo(self.Called):
      @property
      @memoized
      def calls(self):
        return self._called()

    foo1 = Foo(1)
    self.assertEqual(1, foo1.calls)
    self.assertEqual(1, foo1.calls)

    foo2 = Foo(2)
    self.assertEqual(2, foo2.calls)
    self.assertEqual(2, foo2.calls)

  def test_memoized_property(self):
    class Foo(self.Called):
      @memoized_property
      def calls(self):
        return self._called()

    foo1 = Foo(1)
    self.assertEqual(1, foo1.calls)
    self.assertEqual(1, foo1.calls)

    foo2 = Foo(2)
    self.assertEqual(2, foo2.calls)
    self.assertEqual(2, foo2.calls)

  def test_memoized_classmethod(self):
    class Foo(object):
      _calls = 0

      @memoized_classmethod
      def calls(cls):
        cls._calls += len(cls.__name__)
        return cls._calls

    class Bar(Foo):
      pass

    class BamBam(Foo):
      pass

    self.assertEqual(3, Bar.calls())
    self.assertEqual(3, Bar.calls())
    self.assertEqual(6, BamBam.calls())
    self.assertEqual(6, BamBam.calls())
    self.assertEqual(3, Foo.calls())
    self.assertEqual(3, Foo.calls())

  def test_memoized_staticmethod(self):
    class Foo(object):
      _calls = 0

      @memoized_staticmethod
      def calls():
        Foo._calls += 1
        return Foo._calls

    self.assertEqual(1, Foo.calls())
    self.assertEqual(1, Foo.calls())
