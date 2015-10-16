# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.engine.exp.addressable import (Exactly, MutationError, NotSerializableError,
                                          SubclassesOf, SuperclassesOf, TypeConstraintError,
                                          addressable, addressable_dict, addressable_list)
from pants.engine.exp.objects import Resolvable, Serializable


class TypeConstraintTestBase(unittest.TestCase):
  class A(object):
    pass

  class B(A):
    pass

  class C(B):
    pass

  class BPrime(A):
    pass


class SuperclassesOfTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaises(ValueError):
      SubclassesOf()

  def test_single(self):
    self.assertTrue(SuperclassesOf(self.B).satisfied_by(self.A()))
    self.assertTrue(SuperclassesOf(self.B).satisfied_by(self.B()))
    self.assertFalse(SuperclassesOf(self.B).satisfied_by(self.BPrime()))
    self.assertFalse(SuperclassesOf(self.B).satisfied_by(self.C()))

  def test_multiple(self):
    self.assertTrue(SuperclassesOf(self.A, self.B).satisfied_by(self.A()))
    self.assertTrue(SuperclassesOf(self.A, self.B).satisfied_by(self.B()))
    self.assertFalse(SuperclassesOf(self.A, self.B).satisfied_by(self.BPrime()))
    self.assertFalse(SuperclassesOf(self.A, self.B).satisfied_by(self.C()))


class ExactlyTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaises(ValueError):
      Exactly()

  def test_single(self):
    self.assertFalse(Exactly(self.B).satisfied_by(self.A()))
    self.assertTrue(Exactly(self.B).satisfied_by(self.B()))
    self.assertFalse(Exactly(self.B).satisfied_by(self.BPrime()))
    self.assertFalse(Exactly(self.B).satisfied_by(self.C()))

  def test_multiple(self):
    self.assertTrue(Exactly(self.A, self.B).satisfied_by(self.A()))
    self.assertTrue(Exactly(self.A, self.B).satisfied_by(self.B()))
    self.assertFalse(Exactly(self.A, self.B).satisfied_by(self.BPrime()))
    self.assertFalse(Exactly(self.A, self.B).satisfied_by(self.C()))


class SubclassesOfTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaises(ValueError):
      SubclassesOf()

  def test_single(self):
    self.assertFalse(SubclassesOf(self.B).satisfied_by(self.A()))
    self.assertTrue(SubclassesOf(self.B).satisfied_by(self.B()))
    self.assertFalse(SubclassesOf(self.B).satisfied_by(self.BPrime()))
    self.assertTrue(SubclassesOf(self.B).satisfied_by(self.C()))

  def test_multiple(self):
    self.assertTrue(SubclassesOf(self.B, self.C).satisfied_by(self.B()))
    self.assertTrue(SubclassesOf(self.B, self.C).satisfied_by(self.C()))
    self.assertFalse(SubclassesOf(self.B, self.C).satisfied_by(self.BPrime()))
    self.assertFalse(SubclassesOf(self.B, self.C).satisfied_by(self.A()))


class SimpleSerializable(Serializable):
  def __init__(self, **kwargs):
    self._kwargs = kwargs

  def _asdict(self):
    return self._kwargs


class CountingResolvable(Resolvable):
  def __init__(self, address, value):
    self._address = address
    self._value = value
    self._resolutions = 0

  @property
  def address(self):
    return self._address

  def resolve(self):
    try:
      return self._value
    finally:
      self._resolutions += 1

  @property
  def resolutions(self):
    return self._resolutions


class AddressableDescriptorTest(unittest.TestCase):
  def test_inappropriate_application(self):
    class NotSerializable(object):
      def __init__(self, count):
        super(NotSerializable, self).__init__()
        self.count = count

      @addressable(Exactly(int))
      def count(self):
        pass

    with self.assertRaises(NotSerializableError):
      NotSerializable(42)


class AddressableTest(unittest.TestCase):
  class Person(SimpleSerializable):
    def __init__(self, age):
      super(AddressableTest.Person, self).__init__()
      self.age = age

    @addressable(Exactly(int))
    def age(self):
      """Return the person's age in years.

      :rtype int
      """

  def test_none(self):
    person = self.Person(None)

    self.assertIsNone(person.age, None)

  def test_value(self):
    person = self.Person(42)

    self.assertEqual(42, person.age)

  def test_address(self):
    person = self.Person('//:meaning-of-life')

    self.assertEqual('//:meaning-of-life', person.age)

  def test_resolvable(self):
    resolvable_age = CountingResolvable('//:meaning-of-life', 42)
    person = self.Person(resolvable_age)

    self.assertEqual(0, resolvable_age.resolutions)

    self.assertEqual(42, person.age)
    self.assertEqual(1, resolvable_age.resolutions)

    self.assertEqual(42, person.age)
    self.assertEqual(2, resolvable_age.resolutions)

  def test_type_mismatch_value(self):
    with self.assertRaises(TypeConstraintError):
      self.Person(42.0)

  def test_type_mismatch_resolvable(self):
    resolvable_age = CountingResolvable('//:meaning-of-life', 42.0)
    person = self.Person(resolvable_age)

    with self.assertRaises(TypeConstraintError):
      person.age

  def test_single_assignment(self):
    person = self.Person(42)
    with self.assertRaises(MutationError):
      person.age = 37


class AddressableListTest(unittest.TestCase):
  class Series(SimpleSerializable):
    def __init__(self, values):
      super(AddressableListTest.Series, self).__init__()
      self.values = values

    @addressable_list(Exactly(int, float))
    def values(self):
      """Return this series' values.

      :rtype list of int or float
      """

  def test_none(self):
    series = self.Series(None)

    self.assertEqual([], series.values)

  def test_values(self):
    series = self.Series([42, 1 / 137.0])

    self.assertEqual([42, 1 / 137.0], series.values)

  def test_addresses(self):
    series = self.Series(['//:meaning-of-life'])

    self.assertEqual(['//:meaning-of-life'], series.values)

  def test_resolvables(self):
    resolvable_value = CountingResolvable('//:fine-structure-constant', 1 / 137.0)
    series = self.Series([resolvable_value])

    self.assertEqual([1 / 137.0], series.values)
    self.assertEqual(1, resolvable_value.resolutions)

    self.assertEqual(1 / 137.0, series.values[0])
    self.assertEqual(2, resolvable_value.resolutions)

  def test_mixed(self):
    resolvable_value = CountingResolvable('//:fine-structure-constant', 1 / 137.0)
    series = self.Series([42, '//:meaning-of-life', resolvable_value])

    self.assertEqual(0, resolvable_value.resolutions)

    self.assertEqual([42, '//:meaning-of-life', 1 / 137.0], series.values)
    self.assertEqual(1, resolvable_value.resolutions)

    self.assertEqual(1 / 137.0, series.values[2])
    self.assertEqual(2, resolvable_value.resolutions)

  def test_type_mismatch_container(self):
    with self.assertRaises(TypeError):
      self.Series({42, 1 / 137.0})

  def test_type_mismatch_value(self):
    with self.assertRaises(TypeConstraintError):
      self.Series([42, False])

  def test_type_mismatch_resolvable(self):
    resolvable_value = CountingResolvable('//:meaning-of-life', True)
    series = self.Series([42, resolvable_value])

    with self.assertRaises(TypeConstraintError):
      series.values

  def test_single_assignment(self):
    series = self.Series([42])
    with self.assertRaises(MutationError):
      series.values = [37]


class AddressableDictTest(unittest.TestCase):
  class Varz(SimpleSerializable):
    def __init__(self, varz):
      super(AddressableDictTest.Varz, self).__init__()
      self.varz = varz

    @addressable_dict(Exactly(int, float))
    def varz(self):
      """Return a snapshot of the current /varz.

      :rtype dict of string -> int or float
      """

  def test_none(self):
    varz = self.Varz(None)

    self.assertEqual({}, varz.varz)

  def test_values(self):
    varz = self.Varz({'meaning of life': 42, 'fine structure constant': 1 / 137.0})

    self.assertEqual({'meaning of life': 42, 'fine structure constant': 1 / 137.0}, varz.varz)

  def test_addresses(self):
    varz = self.Varz({'meaning of life': '//:meaning-of-life'})

    self.assertEqual({'meaning of life': '//:meaning-of-life'}, varz.varz)

  def test_resolvables(self):
    resolvable_value = CountingResolvable('//:fine-structure-constant', 1 / 137.0)
    varz = self.Varz({'fine structure constant': resolvable_value})

    self.assertEqual({'fine structure constant': 1 / 137.0}, varz.varz)
    self.assertEqual(1, resolvable_value.resolutions)

    self.assertEqual(1 / 137.0, varz.varz['fine structure constant'])
    self.assertEqual(2, resolvable_value.resolutions)

  def test_mixed(self):
    resolvable_value = CountingResolvable('//:fine-structure-constant', 1 / 137.0)
    varz = self.Varz({'prime': 37,
                      'meaning of life': '//:meaning-of-life',
                      'fine structure constant': resolvable_value})

    self.assertEqual(0, resolvable_value.resolutions)

    self.assertEqual({'prime': 37,
                      'meaning of life': '//:meaning-of-life',
                      'fine structure constant': 1 / 137.0},
                     varz.varz)
    self.assertEqual(1, resolvable_value.resolutions)

    self.assertEqual(1 / 137.0, varz.varz['fine structure constant'])
    self.assertEqual(2, resolvable_value.resolutions)

  def test_type_mismatch_container(self):
    with self.assertRaises(TypeError):
      self.Varz([42, 1 / 137.0])

  def test_type_mismatch_value(self):
    with self.assertRaises(TypeConstraintError):
      self.Varz({'meaning of life': 42, 'fine structure constant': False})

  def test_type_mismatch_resolvable(self):
    resolvable_item = CountingResolvable('//:fine-structure-constant', True)
    varz = self.Varz({'meaning of life': 42, 'fine structure constant': resolvable_item})

    with self.assertRaises(TypeConstraintError):
      varz.varz

  def test_single_assignment(self):
    varz = self.Varz({'meaning of life': 42})
    with self.assertRaises(MutationError):
      varz.varz = {'fine structure constant': 1 / 137.0}
