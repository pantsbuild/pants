# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import pickle

from pants.util.objects import (
  Exactly, FieldType, SubclassesOf, SuperclassesOf, TypeCheckError,
  TypeConstraintError, TypedDatatypeClassConstructionError,
  TypedDatatypeInstanceConstructionError, datatype, typed_datatype, typed_data)
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


class AnotherTypedDatatype(typed_datatype('AnotherTypedDatatype', (str, list))):
  """This is an example of successfully using `typed_datatype()` without `@typed_data()`."""


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
      raise cls.make_type_error("value is negative: {!r}.".format(value))

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


class FieldTypeTest(BaseTest):
  def test_field_type_creation(self):
    str_field = FieldType.create_from_type(str)
    self.assertEqual(repr(str_field), "FieldType(str, 'primitive__str')")

    self.assertEqual(str('asdf'),
                     str_field.validate_satisfies_field(str('asdf')))

    with self.assertRaises(TypeConstraintError) as cm:
      str_field.validate_satisfies_field(3)
    expected_msg = (
      "value 3 (with type 'int') must be an instance of type 'str'.")
    self.assertEqual(str(cm.exception), str(expected_msg))

    nonneg_int_field = FieldType.create_from_type(NonNegativeInt)
    self.assertEqual(repr(nonneg_int_field),
                     "FieldType(NonNegativeInt, 'non_negative_int')")

    self.assertEqual(
      NonNegativeInt(45),
      nonneg_int_field.validate_satisfies_field(NonNegativeInt(45)))

    with self.assertRaises(TypeConstraintError) as cm:
      nonneg_int_field.validate_satisfies_field(-3)
    expected_msg = ("value -3 (with type 'int') must be an instance "
                    "of type 'NonNegativeInt'.")
    self.assertEqual(str(cm.exception), str(expected_msg))


class TypedDatatypeTest(BaseTest):

  def test_class_construction_errors(self):
    # NB: typed_datatype subclasses declared at top level are the success cases
    # here by not failing on import.

    # If the type_name can't be converted into a suitable identifier, throw a
    # ValueError.
    with self.assertRaises(ValueError) as cm:
      class NonStrType(typed_datatype(3, (int,))): pass
    expected_msg = "Type names and field names cannot start with a number: '3'"
    self.assertEqual(str(cm.exception), str(expected_msg))

    # This raises a TypeError because it doesn't provide a required argument.
    with self.assertRaises(TypeError) as cm:
      class NoFields(typed_datatype('NoFields')): pass
    expected_msg = "typed_datatype() takes exactly 2 arguments (1 given)"
    self.assertEqual(str(cm.exception), str(expected_msg))

    with self.assertRaises(TypedDatatypeClassConstructionError) as cm:
      class NonTupleFields(typed_datatype('NonTupleFields', [str])): pass
    expected_msg = (
      "error: while trying to generate typed datatype NonTupleFields: "
      "field_decls is not a tuple: [<type 'str'>]")
    self.assertEqual(str(cm.exception), str(expected_msg))

    with self.assertRaises(TypedDatatypeClassConstructionError) as cm:
      class EmptyTupleFields(typed_datatype('EmptyTupleFields', ())): pass
    expected_msg = (
      "error: while trying to generate typed datatype EmptyTupleFields: "
      "no fields were declared")
    self.assertEqual(str(cm.exception), str(expected_msg))

    with self.assertRaises(TypedDatatypeClassConstructionError) as cm:
      class NonTypeFields(typed_datatype('NonTypeFields', (3,))): pass
    expected_msg = (
      "error: while trying to generate typed datatype NonTypeFields: "
      "invalid field declarations:\n"
      "type_obj is not a type: was 3 (<type 'int'>)")
    self.assertEqual(str(cm.exception), str(expected_msg))

  def test_decorator_construction_errors(self):
    with self.assertRaises(TypedDatatypeClassConstructionError) as cm:
      @typed_data(str('hm'))
      class NonTypeFieldDecorated: pass
    expected_msg = (
      "error: while trying to generate typed datatype NonTypeFieldDecorated: "
      "invalid field declarations:\n"
      "type_obj is not a type: was 'hm' (<type 'str'>)")
    self.assertEqual(str(cm.exception), str(expected_msg))

    with self.assertRaises(ValueError) as cm:
      @typed_data(int)
      def some_fun(): pass
    expected_msg = ("The @typed_data() decorator must be applied "
                    "innermost of all decorators.")
    self.assertEqual(str(cm.exception), str(expected_msg))

  def test_instance_construction_by_repr(self):
    some_val = SomeTypedDatatype(3)
    self.assertEqual(3, some_val.primitive__int)
    self.assertEqual(repr(some_val), "SomeTypedDatatype(3)")
    self.assertEqual(str(some_val), "SomeTypedDatatype(primitive__int<int>=3)")

    some_object = YetAnotherNamedTypedDatatype(str('asdf'), 45)
    self.assertEqual(some_object.primitive__str, 'asdf')
    self.assertEqual(some_object.primitive__int, 45)
    self.assertEqual(repr(some_object),
                     "YetAnotherNamedTypedDatatype('asdf', 45)")
    self.assertEqual(
      str(some_object),
      str("YetAnotherNamedTypedDatatype(primitive__str<str>=asdf, primitive__int<int>=45)"))

    some_nonneg_int = NonNegativeInt(3)
    self.assertEqual(3, some_nonneg_int.primitive__int)
    self.assertEqual(repr(some_nonneg_int), "NonNegativeInt(3)")
    self.assertEqual(str(some_nonneg_int),
                     "NonNegativeInt(primitive__int<int>=3)")

    wrapped_nonneg_int = CamelCaseWrapper(NonNegativeInt(45))
    # test attribute naming for camel-cased types
    self.assertEqual(45, wrapped_nonneg_int.non_negative_int.primitive__int)
    # test that repr() is called inside repr(), and str() inside str()
    self.assertEqual(repr(wrapped_nonneg_int),
                     "CamelCaseWrapper(NonNegativeInt(45))")
    self.assertEqual(
      str(wrapped_nonneg_int),
      str("CamelCaseWrapper(non_negative_int<NonNegativeInt>=NonNegativeInt(primitive__int<int>=45))"))

  def test_instance_construction_errors(self):
    with self.assertRaises(TypedDatatypeInstanceConstructionError) as cm:
      SomeTypedDatatype(primitive__int=3)
    expected_msg = (
      """error: in constructor of type SomeTypedDatatype: typed_datatype() subclasses can only be constructed with positional arguments! The class SomeTypedDatatype requires (int,) as arguments.
The args provided were: ().
The kwargs provided were: {'primitive__int': 3}.""")
    self.assertEqual(str(cm.exception), str(expected_msg))

    # not providing all the fields
    with self.assertRaises(TypedDatatypeInstanceConstructionError) as cm:
      SomeTypedDatatype()
    expected_msg = (
      """error: in constructor of type SomeTypedDatatype: 0 args were provided, but expected 1: (int,).
The args provided were: ().""")
    self.assertEqual(str(cm.exception), str(expected_msg))

    # unrecognized fields
    with self.assertRaises(TypedDatatypeInstanceConstructionError) as cm:
      SomeTypedDatatype(3, 4)
    expected_msg = (
      """error: in constructor of type SomeTypedDatatype: 2 args were provided, but expected 1: (int,).
The args provided were: (3, 4).""")
    self.assertEqual(str(cm.exception), str(expected_msg))

    with self.assertRaises(TypedDatatypeInstanceConstructionError) as cm:
      CamelCaseWrapper(non_negative_int=3)
    expected_msg = (
      """error: in constructor of type CamelCaseWrapper: typed_datatype() subclasses can only be constructed with positional arguments! The class CamelCaseWrapper requires (NonNegativeInt,) as arguments.
The args provided were: ().
The kwargs provided were: {'non_negative_int': 3}.""")
    self.assertEqual(str(cm.exception), str(expected_msg))

    # test that kwargs with keywords that aren't field names fail the same way
    with self.assertRaises(TypedDatatypeInstanceConstructionError) as cm:
      CamelCaseWrapper(4, a=3)
    expected_msg = (
      """error: in constructor of type CamelCaseWrapper: typed_datatype() subclasses can only be constructed with positional arguments! The class CamelCaseWrapper requires (NonNegativeInt,) as arguments.
The args provided were: (4,).
The kwargs provided were: {'a': 3}.""")
    self.assertEqual(str(cm.exception), str(expected_msg))

  def test_type_check_errors(self):
    # single type checking failure
    with self.assertRaises(TypeCheckError) as cm:
      SomeTypedDatatype([])
    expected_msg = (
      """error: in constructor of type SomeTypedDatatype: type check error:
field 'primitive__int' was invalid: value [] (with type 'list') must be an instance of type 'int'.""")
    self.assertEqual(str(cm.exception), str(expected_msg))

    # type checking failure with multiple arguments (one is correct)
    with self.assertRaises(TypeCheckError) as cm:
      AnotherTypedDatatype(str('correct'), str('should be list'))
    expected_msg = (
      """error: in constructor of type AnotherTypedDatatype: type check error:
field 'primitive__list' was invalid: value 'should be list' (with type 'str') must be an instance of type 'list'.""")
    self.assertEqual(str(cm.exception), str(expected_msg))

    # type checking failure on both arguments
    with self.assertRaises(TypeCheckError) as cm:
      AnotherTypedDatatype(3, str('should be list'))
    expected_msg = (
      """error: in constructor of type AnotherTypedDatatype: type check error:
field 'primitive__str' was invalid: value 3 (with type 'int') must be an instance of type 'str'.
field 'primitive__list' was invalid: value 'should be list' (with type 'str') must be an instance of type 'list'.""")
    self.assertEqual(str(cm.exception), str(expected_msg))

    with self.assertRaises(TypeCheckError) as cm:
      NonNegativeInt(str('asdf'))
    expected_msg = (
      """error: in constructor of type NonNegativeInt: type check error:
field 'primitive__int' was invalid: value 'asdf' (with type 'str') must be an instance of type 'int'.""")
    self.assertEqual(str(cm.exception), str(expected_msg))

    with self.assertRaises(TypeCheckError) as cm:
      NonNegativeInt(-3)
    expected_msg = (
      """error: in constructor of type NonNegativeInt: type check error:
value is negative: -3.""")
    self.assertEqual(str(cm.exception), str(expected_msg))
