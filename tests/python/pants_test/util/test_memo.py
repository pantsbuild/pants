# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.memo import memoized, memoized_property, per_instance, testable_memoized_property


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

    self.assertEqual([(2, 3), (3, 2)], calculations)

  def test_function_application_kwargs(self):
    calculations = []

    @memoized()
    def multiply(first, second):
      calculations.append((first, second))
      return first * second

    self.assertEqual(6, multiply(first=2, second=3))
    self.assertEqual(6, multiply(second=3, first=2))
    self.assertEqual(6, multiply(first=2, second=3))

    self.assertEqual([(2, 3)], calculations)

  def test_function_application_mixed(self):
    calculations = []

    @memoized
    def func(*args, **kwargs):
      calculations.append((args, kwargs))
      return args, kwargs

    self.assertEqual((('a',), {'fred': 42, 'jane': True}), func('a', fred=42, jane=True))
    self.assertEqual((('a', 42), {'jane': True}), func('a', 42, jane=True))
    self.assertEqual((('a',), {'fred': 42, 'jane': True}), func('a', jane=True, fred=42))

    self.assertEqual([(('a',), {'fred': 42, 'jane': True}),
                      (('a', 42), {'jane': True})], calculations)

  def test_function_application_potentially_ambiguous_parameters(self):
    calculations = []

    @memoized
    def func(*args, **kwargs):
      calculations.append((args, kwargs))
      return args, kwargs

    self.assertEqual(((('a', 42),), {}), func(('a', 42)))
    self.assertEqual(((), {'a': 42}), func(a=42))

    self.assertEqual([((('a', 42),), {}),
                      ((), {'a': 42})], calculations)

  def test_key_factory(self):
    def create_key(num):
      return num % 2

    calculations = []

    @memoized(key_factory=create_key)
    def square(num):
      calculations.append(num)
      return num * num

    self.assertEqual(4, square(2))
    self.assertEqual(9, square(3))
    self.assertEqual(4, square(4))
    self.assertEqual(9, square(5))
    self.assertEqual(4, square(8))
    self.assertEqual(9, square(7))

    self.assertEqual([2, 3], calculations)

  def test_cache_factory(self):
    class SingleEntryMap(dict):
      def __setitem__(self, key, value):
        self.clear()
        return super(SingleEntryMap, self).__setitem__(key, value)

    calculations = []

    @memoized(cache_factory=SingleEntryMap)
    def square(num):
      calculations.append(num)
      return num * num

    self.assertEqual(4, square(2))
    self.assertEqual(4, square(2))
    self.assertEqual(9, square(3))
    self.assertEqual(9, square(3))
    self.assertEqual(4, square(2))
    self.assertEqual(4, square(2))

    self.assertEqual([2, 3, 2], calculations)

  def test_forget(self):
    calculations = []

    @memoized
    def square(num):
      calculations.append(num)
      return num * num

    self.assertEqual(4, square(2))
    self.assertEqual(4, square(2))
    self.assertEqual(9, square(3))
    self.assertEqual(9, square(3))

    square.forget(2)

    self.assertEqual(4, square(2))
    self.assertEqual(4, square(2))
    self.assertEqual(9, square(3))
    self.assertEqual(9, square(3))

    self.assertEqual([2, 3, 2], calculations)

  def test_clear(self):
    calculations = []

    @memoized
    def square(num):
      calculations.append(num)
      return num * num

    self.assertEqual(4, square(2))
    self.assertEqual(4, square(2))
    self.assertEqual(9, square(3))
    self.assertEqual(9, square(3))

    square.clear()

    self.assertEqual(4, square(2))
    self.assertEqual(4, square(2))
    self.assertEqual(9, square(3))
    self.assertEqual(9, square(3))

    self.assertEqual([2, 3, 2, 3], calculations)

  class _Called(object):
    def __init__(self, increment):
      self._calls = 0
      self._increment = increment

    def _called(self):
      self._calls += self._increment
      return self._calls

  def test_instancemethod_application_id_eq(self):
    class Foo(self._Called):
      @memoized
      def calls(self):
        return self._called()

    foo1 = Foo(1)
    foo2 = Foo(2)

    # Different (`!=`) Foo instances have their own cache:
    self.assertEqual(1, foo1.calls())
    self.assertEqual(1, foo1.calls())

    self.assertEqual(2, foo2.calls())
    self.assertEqual(2, foo2.calls())

  def test_instancemethod_application_degenerate_eq(self):
    class Foo(self._Called):
      @memoized
      def calls_per_eq(self):
        return self._called()

      @memoized(key_factory=per_instance)
      def calls_per_instance(self):
        return self._called()

      def __hash__(self):
        return hash(type)

      def __eq__(self, other):
        return type(self) == type(other)

    foo1 = Foo(3)
    foo2 = Foo(4)

    # Here foo1 and foo2 share a cache since they are `==` which is likely surprising behavior:
    self.assertEqual(3, foo1.calls_per_eq())
    self.assertEqual(3, foo1.calls_per_eq())

    self.assertEqual(3, foo2.calls_per_eq())
    self.assertEqual(3, foo2.calls_per_eq())

    # Here the cache is split between the instances which is likely the expected behavior:
    self.assertEqual(6, foo1.calls_per_instance())
    self.assertEqual(6, foo1.calls_per_instance())

    self.assertEqual(4, foo2.calls_per_instance())
    self.assertEqual(4, foo2.calls_per_instance())

  def test_descriptor_application_invalid(self):
    with self.assertRaises(ValueError):
      # Can't decorate a descriptor
      class Foo(object):
        @memoized
        @property
        def name(self):
          pass

  def test_descriptor_application_valid(self):
    class Foo(self._Called):
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
    class Foo(self._Called):
      @memoized_property
      def calls(self):
        return self._called()

    foo1 = Foo(1)
    self.assertEqual(1, foo1.calls)
    self.assertEqual(1, foo1.calls)

    foo2 = Foo(2)
    self.assertEqual(2, foo2.calls)
    self.assertEqual(2, foo2.calls)

    with self.assertRaises(AttributeError):
      foo2.calls = None

  def test_mutable_memoized_property(self):
    class Foo(self._Called):
      @testable_memoized_property
      def calls(self):
        return self._called()

    foo1 = Foo(1)
    self.assertEqual(1, foo1.calls)
    self.assertEqual(1, foo1.calls)

    foo2 = Foo(2)
    self.assertEqual(2, foo2.calls)
    self.assertEqual(2, foo2.calls)

    foo2.calls = None
    self.assertIsNone(foo2.calls)

  def test_memoized_property_forget(self):
    class Foo(self._Called):
      @memoized_property
      def calls(self):
        return self._called()

    foo1 = Foo(1)

    # Forgetting before caching should be a harmless noop
    del foo1.calls

    self.assertEqual(1, foo1.calls)
    self.assertEqual(1, foo1.calls)

    foo2 = Foo(2)
    self.assertEqual(2, foo2.calls)
    self.assertEqual(2, foo2.calls)

    # Now un-cache foo2's calls result and observe no effect on foo1.calls, but a re-compute for
    # foo2.calls
    del foo2.calls

    self.assertEqual(1, foo1.calls)
    self.assertEqual(1, foo1.calls)

    self.assertEqual(4, foo2.calls)
    self.assertEqual(4, foo2.calls)
