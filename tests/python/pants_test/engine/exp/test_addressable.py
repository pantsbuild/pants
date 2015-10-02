# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.engine.exp.addressable import (Addressed, AddressedError, Exactly, SubclassesOf,
                                          SuperclassesOf, addressable, addressable_mapping,
                                          addressables)


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
  def test(self):
    self.assertTrue(SuperclassesOf(self.B).satisfied_by(self.A()))
    self.assertTrue(SuperclassesOf(self.B).satisfied_by(self.B()))
    self.assertFalse(SuperclassesOf(self.B).satisfied_by(self.BPrime()))
    self.assertFalse(SuperclassesOf(self.B).satisfied_by(self.C()))


class ExactlyTest(TypeConstraintTestBase):
  def test(self):
    self.assertFalse(Exactly(self.B).satisfied_by(self.A()))
    self.assertTrue(Exactly(self.B).satisfied_by(self.B()))
    self.assertFalse(Exactly(self.B).satisfied_by(self.BPrime()))
    self.assertFalse(Exactly(self.B).satisfied_by(self.C()))


class SubclassesOfTest(TypeConstraintTestBase):
  def test(self):
    self.assertFalse(SubclassesOf(self.B).satisfied_by(self.A()))
    self.assertTrue(SubclassesOf(self.B).satisfied_by(self.B()))
    self.assertFalse(SubclassesOf(self.B).satisfied_by(self.BPrime()))
    self.assertTrue(SubclassesOf(self.B).satisfied_by(self.C()))


class AddressableTest(unittest.TestCase):
  def test_none(self):
    self.assertIsNone(addressable(Exactly(int), None))

  def test_value(self):
    self.assertEqual(42, addressable(Exactly(int), 42))

  def test_pointer(self):
    self.assertEqual(Addressed(Exactly(int), '//:meaning-of-life'),
                     addressable(Exactly(int), '//:meaning-of-life'))

  def test_type_mismatch(self):
    with self.assertRaises(AddressedError):
      addressable(Exactly(int), 42.0)


class AddressablesTest(unittest.TestCase):
  def test_none(self):
    self.assertEqual([], addressables(Exactly(int), None))

  def test_values(self):
    self.assertEqual([42, 1 / 137.0], addressables(SubclassesOf((int, float)), (42, 1 / 137.0)))

  def test_pointers(self):
    self.assertEqual([Addressed(Exactly(int), '//:meaning-of-life')],
                     addressables(Exactly(int), ['//:meaning-of-life']))

  def test_mixed(self):
    self.assertEqual([42, Addressed(Exactly(int), '//:meaning-of-life')],
                     addressables(Exactly(int), [42, '//:meaning-of-life']))

  def test_type_mismatch(self):
    with self.assertRaises(AddressedError):
      addressables(Exactly(int), [42, 1 / 137.0])


class AddressableMappingTest(unittest.TestCase):
  def test_none(self):
    self.assertEqual({}, addressable_mapping(Exactly(int), None))

  def test_values(self):
    self.assertEqual(dict(meaning_of_life=42, fine_structure_constant=1 / 137.0),
                     addressable_mapping(SubclassesOf((int, float)),
                                         dict(meaning_of_life=42,
                                              fine_structure_constant=1 / 137.0)))

  def test_pointers(self):
    self.assertEqual(dict(meaning_of_life=Addressed(Exactly(int), '//:meaning-of-life')),
                     addressable_mapping(Exactly(int), dict(meaning_of_life='//:meaning-of-life')))

  def test_mixed(self):
    self.assertEqual(dict(meaning_of_life=42,
                          fine_structure_constant=Addressed(SubclassesOf((int, float)), '//:fsc')),
                     addressable_mapping(SubclassesOf((int, float)),
                                         dict(meaning_of_life=42,
                                              fine_structure_constant='//:fsc')))

  def test_type_mismatch(self):
    with self.assertRaises(AddressedError):
      addressable_mapping(Exactly(int), dict(meaning_of_life=42, fine_structure_constant=1 / 137.0))
