# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import pickle

from pants.util.objects import (
  Exactly, SubclassesOf, SuperclassesOf, TypeCheckError, TypeConstraintError,
  TypedDatatypeClassConstructionError,
  TypedDatatypeInstanceConstructionError,
  datatype, typed_datatype, typed_data)
from pants_test.base_test import BaseTest


class TypeConstraintTestBase(BaseTest):
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
    superclasses_of_b = SuperclassesOf(self.B)
    self.assertEqual((self.B,), superclasses_of_b.types)
    self.assertTrue(superclasses_of_b.satisfied_by(self.A()))
    self.assertTrue(superclasses_of_b.satisfied_by(self.B()))
    self.assertFalse(superclasses_of_b.satisfied_by(self.BPrime()))
    self.assertFalse(superclasses_of_b.satisfied_by(self.C()))

  def test_multiple(self):
    superclasses_of_a_or_b = SuperclassesOf(self.A, self.B)
    self.assertEqual((self.A, self.B), superclasses_of_a_or_b.types)
    self.assertTrue(superclasses_of_a_or_b.satisfied_by(self.A()))
    self.assertTrue(superclasses_of_a_or_b.satisfied_by(self.B()))
    self.assertFalse(superclasses_of_a_or_b.satisfied_by(self.BPrime()))
    self.assertFalse(superclasses_of_a_or_b.satisfied_by(self.C()))


class ExactlyTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaises(ValueError):
      Exactly()

  def test_single(self):
    exactly_b = Exactly(self.B)
    self.assertEqual((self.B,), exactly_b.types)
    self.assertFalse(exactly_b.satisfied_by(self.A()))
    self.assertTrue(exactly_b.satisfied_by(self.B()))
    self.assertFalse(exactly_b.satisfied_by(self.BPrime()))
    self.assertFalse(exactly_b.satisfied_by(self.C()))

  def test_multiple(self):
    exactly_a_or_b = Exactly(self.A, self.B)
    self.assertEqual((self.A, self.B), exactly_a_or_b.types)
    self.assertTrue(exactly_a_or_b.satisfied_by(self.A()))
    self.assertTrue(exactly_a_or_b.satisfied_by(self.B()))
    self.assertFalse(exactly_a_or_b.satisfied_by(self.BPrime()))
    self.assertFalse(exactly_a_or_b.satisfied_by(self.C()))

  def test_disallows_unsplatted_lists(self):
    with self.assertRaises(TypeError):
      Exactly([1])

  def test_str_and_repr(self):
    exactly_b_types = Exactly(self.B, description='B types')
    self.assertEquals("=(B types)", str(exactly_b_types))
    self.assertEquals("Exactly(B types)", repr(exactly_b_types))

    exactly_b = Exactly(self.B)
    self.assertEquals("=B", str(exactly_b))
    self.assertEquals("Exactly(B)", repr(exactly_b))

    exactly_multiple = Exactly(self.A, self.B)
    self.assertEquals("=(A, B)", str(exactly_multiple))
    self.assertEquals("Exactly(A, B)", repr(exactly_multiple))

  def test_checking_via_bare_type(self):
    self.assertTrue(Exactly(self.B).satisfied_by_type(self.B))
    self.assertFalse(Exactly(self.B).satisfied_by_type(self.C))


class SubclassesOfTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaises(ValueError):
      SubclassesOf()

  def test_single(self):
    subclasses_of_b = SubclassesOf(self.B)
    self.assertEqual((self.B,), subclasses_of_b.types)
    self.assertFalse(subclasses_of_b.satisfied_by(self.A()))
    self.assertTrue(subclasses_of_b.satisfied_by(self.B()))
    self.assertFalse(subclasses_of_b.satisfied_by(self.BPrime()))
    self.assertTrue(subclasses_of_b.satisfied_by(self.C()))

  def test_multiple(self):
    subclasses_of_b_or_c = SubclassesOf(self.B, self.C)
    self.assertEqual((self.B, self.C), subclasses_of_b_or_c.types)
    self.assertTrue(subclasses_of_b_or_c.satisfied_by(self.B()))
    self.assertTrue(subclasses_of_b_or_c.satisfied_by(self.C()))
    self.assertFalse(subclasses_of_b_or_c.satisfied_by(self.BPrime()))
    self.assertFalse(subclasses_of_b_or_c.satisfied_by(self.A()))


class ExportedDatatype(datatype('ExportedDatatype', ['val'])):
  pass


class AbsClass(object):
  pass


# TODO: add a test with at least one mixin or something!
@typed_data(int)
class SomeTypedDatatype: pass


@typed_data(str, list)
class AnotherTypedDatatype: pass


@typed_data(str, int)
class YetAnotherNamedTypedDatatype: pass


@typed_data(int)
class NonNegativeInt:
  "???"

  # NB: TypedDatatype.__new__() will raise if any kwargs are provided, but
  # subclasses are free to use kwargs as long as they don't pass them on to the
  # TypedDatatype constructor.
  def __new__(cls, *args, **kwargs):
    # Call the superclass ctor first to ensure the type is correct.
    this_object = super(NonNegativeInt, cls).__new__(cls, *args, **kwargs)

    value = this_object.primitive__int

    if value < 0:
      # TODO: make a method to do this without having to provide the class name.
      raise TypeCheckError(
        cls.__name__, "value is negative: '{}'".format(value))

    return this_object


@typed_data(NonNegativeInt)
class CamelCaseWrapper: pass


class ReturnsNotImplemented(object):
  def __eq__(self, other):
    return NotImplemented


class DatatypeTest(BaseTest):

  def test_eq_with_not_implemented_super(self):
    class DatatypeSuperNotImpl(datatype('Foo', ['val']), ReturnsNotImplemented, tuple):
      pass

    self.assertNotEqual(DatatypeSuperNotImpl(1), DatatypeSuperNotImpl(1))

  def test_type_included_in_eq(self):
    foo = datatype('Foo', ['val'])
    bar = datatype('Bar', ['val'])

    self.assertFalse(foo(1) == bar(1))
    self.assertTrue(foo(1) != bar(1))

  def test_subclasses_not_equal(self):
    foo = datatype('Foo', ['val'])
    class Bar(foo):
      pass

    self.assertFalse(foo(1) == Bar(1))
    self.assertTrue(foo(1) != Bar(1))

  def test_repr(self):
    bar = datatype('Bar', ['val', 'zal'])
    self.assertEqual('Bar(val=1, zal=1)', repr(bar(1, 1)))

    class Foo(datatype('F', ['val']), AbsClass):
      pass

    # Maybe this should be 'Foo(val=1)'?
    self.assertEqual('F(val=1)', repr(Foo(1)))

  def test_not_iterable(self):
    bar = datatype('Bar', ['val'])
    with self.assertRaises(TypeError):
      for x in bar(1):
        pass

  def test_deep_copy(self):
    # deep copy calls into __getnewargs__, which namedtuple defines as implicitly using __iter__.

    bar = datatype('Bar', ['val'])

    self.assertEqual(bar(1), copy.deepcopy(bar(1)))

  def test_atrs(self):
    bar = datatype('Bar', ['val'])
    self.assertEqual(1, bar(1).val)

  def test_as_dict(self):
    bar = datatype('Bar', ['val'])

    self.assertEqual({'val': 1}, bar(1)._asdict())

  def test_replace_non_iterable(self):
    bar = datatype('Bar', ['val', 'zal'])

    self.assertEqual(bar(1, 3), bar(1, 2)._replace(zal=3))

  def test_properties_not_assignable(self):
    bar = datatype('Bar', ['val'])
    bar_inst = bar(1)
    with self.assertRaises(AttributeError):
      bar_inst.val = 2

  def test_invalid_field_name(self):
    with self.assertRaises(ValueError):
      datatype('Bar', ['0isntanallowedfirstchar'])

  def test_subclass_pickleable(self):
    before = ExportedDatatype(1)
    dumps = pickle.dumps(before, protocol=2)
    after = pickle.loads(dumps)
    self.assertEqual(before, after)

  def test_mixed_argument_types(self):
    bar = datatype('Bar', ['val', 'zal'])
    self.assertEqual(bar(1, 2), bar(val=1, zal=2))
    self.assertEqual(bar(1, 2), bar(zal=2, val=1))

  def test_double_passed_arg(self):
    bar = datatype('Bar', ['val', 'zal'])
    with self.assertRaises(TypeError):
      bar(1, val=1)

  def test_too_many_args(self):
    bar = datatype('Bar', ['val', 'zal'])
    with self.assertRaises(TypeError):
      bar(1, 1, 1)

  def test_unexpect_kwarg(self):
    bar = datatype('Bar', ['val'])
    with self.assertRaises(TypeError):
      bar(other=1)


class TypedDatatypeTest(BaseTest):

  def test_class_construction(self):
    # NB: typed_datatype subclasses declared at top level are the success cases
    # here by not failing on import.

    # If the type_name can't be converted into a suitable identifier, throw a
    # ValueError.
    with self.assertRaises(ValueError):
      class NonStrType(typed_datatype(3, (int,))): pass

    # This raises a TypeError because it doesn't provide a required argument.
    with self.assertRaises(TypeError):
      class NoFields(typed_datatype('NoFields')): pass

    with self.assertRaises(TypedDatatypeClassConstructionError):
      class NonTupleTypeFields(typed_datatype('NonTupleTypeFields', [str])):
        pass

    with self.assertRaises(TypedDatatypeClassConstructionError):
      class NonTypeFields(typed_datatype('NonTypeFields', (3,))): pass

  def test_instance_construction(self):

    # TODO: test with non-primitive types as well, lol
    some_val = SomeTypedDatatype(3)
    self.assertIn('SomeTypedDatatype', repr(some_val))
    self.assertIn('primitive__int', repr(some_val))
    self.assertIn('3', repr(some_val))

    some_object = YetAnotherNamedTypedDatatype(str('asdf'), 3)
    self.assertEqual(3, some_object.primitive__int)

    with self.assertRaises(TypeCheckError):
      SomeTypedDatatype([])

    # TODO: FIX THIS: ensure construction with any kwargs has its own
    # exception!! also check incorrect number of args!
    with self.assertRaises(TypedDatatypeInstanceConstructionError):
      SomeTypedDatatype(primitive__int=3)

    # not providing all the fields
    try:
      SomeTypedDatatype()
      self.fail("should have errored: not providing all constructor fields")
    except TypedDatatypeInstanceConstructionError as e:
      self.assertIn('primitive__int', str(e))

    # unrecognized fields
    try:
      SomeTypedDatatype(3, 4)
      self.fail("should have an unrecognized field error")
    except TypedDatatypeInstanceConstructionError as e:
      self.assertIn('(3, 4)', str(e))

    # type checking failures
    with self.assertRaises(TypeCheckError):
      SomeTypedDatatype('not a number')

    with self.assertRaises(TypeCheckError):
      NonNegativeInt('asdf')

    with self.assertRaises(TypeCheckError):
      NonNegativeInt(-3)

    some_nonneg_int = NonNegativeInt(3)
    self.assertEqual(3, some_nonneg_int.primitive__int)

    some_wrapped_nonneg_int = CamelCaseWrapper(NonNegativeInt(45))
    self.assertEqual(45, some_wrapped_nonneg_int.non_negative_int.primitive__int)

    try:
      AnotherTypedDatatype(3, 3)
      self.fail("should have had a type check error")
    except TypeCheckError as e:
      self.assertIn('primitive__str', str(e))
      self.assertIn('primitive__list', str(e))
