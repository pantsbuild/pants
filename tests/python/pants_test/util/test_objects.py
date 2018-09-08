# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import pickle
import re
from abc import abstractmethod
from builtins import object, str

from future.utils import PY3, text_type

from pants.util.objects import DatatypeFieldDecl as F
from pants.util.objects import Exactly, SubclassesOf, SuperclassesOf, TypeCheckError, datatype, enum
from pants_test.test_base import TestBase


class TypeConstraintTestBase(TestBase):
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
    self.assertEqual("=(B types)", str(exactly_b_types))
    self.assertEqual("Exactly(B types)", repr(exactly_b_types))

    exactly_b = Exactly(self.B)
    self.assertEqual("=B", str(exactly_b))
    self.assertEqual("Exactly(B)", repr(exactly_b))

    exactly_multiple = Exactly(self.A, self.B)
    self.assertEqual("=(A, B)", str(exactly_multiple))
    self.assertEqual("Exactly(A, B)", repr(exactly_multiple))

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


class ExportedDatatype(datatype(['val'])):
  pass


class AbsClass(object):
  pass


class SomeTypedDatatype(datatype([('val', int)])): pass


class SomeMixin(object):

  @abstractmethod
  def as_str(self): pass

  def stripped(self):
    return self.as_str().strip()


# These datatype() calls with strings or tuples for fields are interpreted into a DatatypeFieldDecl
# by DatatypeFieldDecl.parse().
class TypedWithMixin(datatype([('val', text_type)]), SomeMixin):
  """Example of using `datatype()` with a mixin."""

  def as_str(self):
    return self.val


class AnotherTypedDatatype(datatype([('string', text_type), ('elements', list)])): pass


class WithExplicitTypeConstraint(datatype([('a_string', text_type), ('an_int', Exactly(int))])): pass


class MixedTyping(datatype(['value', ('name', text_type)])): pass


# `F` is what we imported `pants.util.objects.DatatypeFieldDecl` as.
class WithDefaultValueTuple(datatype([
    F('an_int', int, default_value=3),
])): pass


class WithJustDefaultValueExplicitFieldDecl(datatype([
    F('a_bool', Exactly(bool), default_value=True),
])): pass


class SomeBaseClass(object):
  @abstractmethod
  def something(self): pass


class SomeDatatypeClass(SomeBaseClass):
  def something(self):
    return 'asdf'

  def __repr__(self):
    return 'SomeDatatypeClass()'


class WithSubclassTypeConstraint(datatype([('some_value', SubclassesOf(SomeBaseClass))])): pass


class NonNegativeInt(datatype([('an_int', int)])):
  """Example of overriding __new__() to perform deeper argument checking."""

  # NB: __new__() in the class returned by datatype() will raise if any kwargs are provided, but
  # subclasses are free to pass around kwargs as long as they don't forward them to that particular
  # __new__() method.
  def __new__(cls, *args, **kwargs):
    # Call the superclass ctor first to ensure the type is correct.
    this_object = super(NonNegativeInt, cls).__new__(cls, *args, **kwargs)

    value = this_object.an_int

    if value < 0:
      raise cls.make_type_error("value is negative: {!r}.".format(value))

    return this_object


class CamelCaseWrapper(datatype([('nonneg_int', NonNegativeInt)])): pass


class ReturnsNotImplemented(object):
  def __eq__(self, other):
    return NotImplemented


class SomeEnum(enum('x', [1, 2])): pass


class DatatypeTest(TestBase):

  def test_eq_with_not_implemented_super(self):
    class DatatypeSuperNotImpl(datatype(['val']), ReturnsNotImplemented, tuple):
      pass

    self.assertNotEqual(DatatypeSuperNotImpl(1), DatatypeSuperNotImpl(1))

  def test_type_included_in_eq(self):
    foo = datatype(['val'])
    bar = datatype(['val'])

    self.assertFalse(foo(1) == bar(1))
    self.assertTrue(foo(1) != bar(1))

  def test_subclasses_not_equal(self):
    foo = datatype(['val'])
    class Bar(foo):
      pass

    self.assertFalse(foo(1) == Bar(1))
    self.assertTrue(foo(1) != Bar(1))

  def test_repr(self):
    bar = datatype(['val', 'zal'], superclass_name='Bar')
    self.assertEqual('Bar(val=1, zal=1)', repr(bar(1, 1)))

    class Foo(datatype(['val'], superclass_name='F'), AbsClass):
      pass

    self.assertEqual('Foo(val=1)', repr(Foo(1)))

  def test_not_iterable(self):
    bar = datatype(['val'])
    with self.assertRaises(TypeError):
      for x in bar(1):
        pass

  def test_deep_copy(self):
    # deep copy calls into __getnewargs__, which namedtuple defines as implicitly using __iter__.

    bar = datatype(['val'])

    self.assertEqual(bar(1), copy.deepcopy(bar(1)))

  def test_atrs(self):
    bar = datatype(['val'])
    self.assertEqual(1, bar(1).val)

  def test_as_dict(self):
    bar = datatype(['val'])

    self.assertEqual({'val': 1}, bar(1)._asdict())

  def test_replace_non_iterable(self):
    bar = datatype(['val', 'zal'])

    self.assertEqual(bar(1, 3), bar(1, 2)._replace(zal=3))

  def test_properties_not_assignable(self):
    bar = datatype(['val'])
    bar_inst = bar(1)
    with self.assertRaises(AttributeError):
      bar_inst.val = 2

  def test_invalid_field_name(self):
    with self.assertRaises(ValueError):
      datatype(['0isntanallowedfirstchar'])

  def test_override_eq_disallowed(self):
    class OverridesEq(datatype(['myval'])):
      def __eq__(self, other):
        return other.myval == self.myval
    with self.assertRaises(TypeCheckError) as tce:
      OverridesEq(1)
    self.assertIn('Should not override __eq__.', str(tce.exception))

  def test_subclass_pickleable(self):
    before = ExportedDatatype(1)
    dumps = pickle.dumps(before, protocol=2)
    after = pickle.loads(dumps)
    self.assertEqual(before, after)

  def test_mixed_argument_types(self):
    bar = datatype(['val', 'zal'])
    self.assertEqual(bar(1, 2), bar(val=1, zal=2))
    self.assertEqual(bar(1, 2), bar(zal=2, val=1))

  def test_double_passed_arg(self):
    bar = datatype(['val', 'zal'])
    with self.assertRaises(TypeError):
      bar(1, val=1)

  def test_too_many_args(self):
    bar = datatype(['val', 'zal'])
    with self.assertRaises(TypeError):
      bar(1, 1, 1)

  def test_unexpect_kwarg(self):
    bar = datatype(['val'])
    with self.assertRaises(TypeError):
      bar(other=1)


class TypedDatatypeTest(TestBase):

  unicode_literal = '' if PY3 else 'u'

  def test_class_construction_errors(self):
    # NB: datatype subclasses declared at top level are the success cases
    # here by not failing on import.

    # If the type_name can't be converted into a suitable identifier, raise a FieldDeclarationError.
    expected_rx_str = re.escape(
      "The field declaration <type 'int'> must be a <type 'unicode'>, tuple, or 'DatatypeFieldDecl' instance, but its type was: 'type'.")
    with self.assertRaisesRegexp(F.FieldDeclarationError, expected_rx_str):
      class NonStrType(datatype([int])): pass

    # This raises a TypeError because it doesn't provide a required argument.
    with self.assertRaises(TypeError) as cm:
      class NoFields(datatype()): pass
    expected_msg = (
      "datatype() missing 1 required positional argument: 'field_decls'"
      if PY3 else
      "datatype() takes at least 1 argument (0 given)"
    )
    self.assertEqual(str(cm.exception), expected_msg)

    expected_rx_str = re.escape(
      "The field declaration {text_t!r} must be a {text_t!r}, tuple, or 'DatatypeFieldDecl' instance, but its type was: 'type'."
      .format(text_t=text_type))
    with self.assertRaisesRegexp(F.FieldDeclarationError, expected_rx_str):
      class JustTypeField(datatype([text_type])): pass

    expected_rx_str = re.escape(
      "The field declaration 3 must be a {text_t!r}, tuple, or 'DatatypeFieldDecl' instance, but its type was: 'int'."
      .format(text_t=text_type))
    with self.assertRaisesRegexp(F.FieldDeclarationError, expected_rx_str):
      class NonStringField(datatype([3])): pass

    with self.assertRaises(ValueError) as cm:
      class NonStringTypeField(datatype([(32, int)])): pass
    expected_msg = (
      "Type names and field names must be valid identifiers: '32'"
      if PY3 else
      "Type names and field names cannot start with a number: '32'"
    )
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(ValueError) as cm:
      class MultipleSameName(datatype([
          'field_a',
          'field_b',
          'field_a',
      ])):
        pass
    expected_msg = "Encountered duplicate field name: 'field_a'"
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(ValueError) as cm:
      class MultipleSameNameWithType(datatype([
            'field_a',
            ('field_a', int),
          ])):
        pass
    expected_msg = "Encountered duplicate field name: 'field_a'"
    self.assertEqual(str(cm.exception), expected_msg)

    expected_rx_str = re.escape(
      "type_constraint for field 'a_field' must be an instance of `type` or `TypeConstraint`, or else None, but was instead 2 (type 'int').")
    with self.assertRaisesRegexp(TypeError, expected_rx_str):
      class InvalidTypeSpec(datatype([('a_field', 2)])): pass

  def test_class_construction_default_value(self):
    with self.assertRaisesRegexp(ValueError, re.escape("Empty tuple () passed to datatype().")):
      class WithEmptyTuple(datatype([()])): pass

    class WithKnownDefaultValueFromTypeConstraint(datatype([F('x', int, default_value=0)])): pass
    self.assertEqual(WithKnownDefaultValueFromTypeConstraint().x, 0)
    self.assertEqual(WithKnownDefaultValueFromTypeConstraint(4).x, 4)
    expected_rx_str = re.escape(
      """error: in constructor of type WithKnownDefaultValueFromTypeConstraint: type check error:
field 'x' was invalid: value None (with type 'NoneType') must satisfy this type constraint: Exactly(int).""")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      WithKnownDefaultValueFromTypeConstraint(None)

    class BrokenTypeConstraint(Exactly):
      has_default_value = True

      def __init__(self, type_to_wrap, default_value):
        super(BrokenTypeConstraint, self).__init__(type_to_wrap)
        self.default_value = default_value

      def __repr__(self):
        return '{}({})'.format(type(self).__name__, self.types[0])

    expected_rx_str = re.escape(
      "default_value 3 for the field 'x' must satisfy the provided type_constraint "
      "BrokenTypeConstraint({})."
      .format(text_type))
    with self.assertRaisesRegexp(TypeError, expected_rx_str):
      class WithBrokenTypeConstraint(datatype([('x', BrokenTypeConstraint(text_type, 3))])): pass

    # This could just be a tuple, but the keyword in the F constructor adds clarity. This works
    # because of the expanded type constraint.
    class WithCheckedDefaultValue(datatype([
        F('x', Exactly(int, type(None)), default_value=None)]
    )): pass
    self.assertEqual(WithCheckedDefaultValue().x, None)
    self.assertEqual(WithCheckedDefaultValue(3).x, 3)
    self.assertEqual(WithCheckedDefaultValue(x=3).x, 3)

    expected_rx_str = re.escape(
      "There are too many elements of the tuple ({unicode_literal}'x', <{class_type} 'int'>, None) passed to datatype(). The tuple must have between 1 and 2 elements. The remaining elements were: [None]."
      .format(unicode_literal=self.unicode_literal,
              class_type=('class' if PY3 else 'type')))
    with self.assertRaisesRegexp(ValueError, expected_rx_str):
      class WithTooManyElementsTuple(datatype([('x', int, None)])): pass

    expected_msg_ending = (
      "__new__() takes from 2 to 3 positional arguments but 4 were given"
      if PY3 else
      "__new__() takes at most 3 arguments (4 given)"
    )
    with self.assertRaisesRegexp(TypeError, re.escape(expected_msg_ending)):
      class WithTooManyPositionalArgsForFieldDecl(datatype([F('x', int, None)])): pass

    expected_msg_ending = (
      "__new__() takes from 2 to 3 positional arguments but 5 were given"
      if PY3 else
      "__new__() takes at most 3 arguments (5 given)"
    )
    with self.assertRaisesRegexp(TypeError, re.escape(expected_msg_ending)):
      class WithUnknownKwargForFieldDecl(datatype([
          F('x', int, None, should_have_default=False)
      ])): pass

  def test_instance_construction_default_value(self):
    self.assertEqual(WithDefaultValueTuple().an_int, 3)
    self.assertEqual(WithDefaultValueTuple(4).an_int, 4)
    self.assertEqual(WithDefaultValueTuple(an_int=4).an_int, 4)

  def test_instance_construction_by_repr(self):
    some_val = SomeTypedDatatype(3)
    self.assertEqual(3, some_val.val)
    self.assertEqual(repr(some_val), "SomeTypedDatatype(val=3)")
    self.assertEqual(str(some_val), "SomeTypedDatatype(val<=int>=3)")

    some_object = WithExplicitTypeConstraint(text_type('asdf'), 45)
    self.assertEqual(some_object.a_string, 'asdf')
    self.assertEqual(some_object.an_int, 45)
    expected_repr = ("WithExplicitTypeConstraint(a_string={unicode_literal}'asdf', an_int=45)"
                     .format(unicode_literal=self.unicode_literal))
    self.assertEqual(repr(some_object), expected_repr)
    expected_str = ("WithExplicitTypeConstraint(a_string<={}>=asdf, an_int<=int>=45)"
                    .format(text_type.__name__))
    self.assertEqual(str(some_object), expected_str)

    some_nonneg_int = NonNegativeInt(an_int=3)
    self.assertEqual(3, some_nonneg_int.an_int)
    self.assertEqual(repr(some_nonneg_int), "NonNegativeInt(an_int=3)")
    self.assertEqual(str(some_nonneg_int), "NonNegativeInt(an_int<=int>=3)")

    wrapped_nonneg_int = CamelCaseWrapper(NonNegativeInt(45))
    # test attribute naming for camel-cased types
    self.assertEqual(45, wrapped_nonneg_int.nonneg_int.an_int)
    # test that repr() is called inside repr(), and str() inside str()
    self.assertEqual(repr(wrapped_nonneg_int),
                     "CamelCaseWrapper(nonneg_int=NonNegativeInt(an_int=45))")
    self.assertEqual(
      str(wrapped_nonneg_int),
      "CamelCaseWrapper(nonneg_int<=NonNegativeInt>=NonNegativeInt(an_int<=int>=45))")

    mixed_type_obj = MixedTyping(value=3, name=text_type('asdf'))
    self.assertEqual(3, mixed_type_obj.value)
    expected_repr = ("MixedTyping(value=3, name={unicode_literal}'asdf')"
                     .format(unicode_literal=self.unicode_literal))
    self.assertEqual(repr(mixed_type_obj), expected_repr)
    expected_str = "MixedTyping(value=3, name<={}>=asdf)".format(text_type.__name__)
    self.assertEqual(str(mixed_type_obj), expected_str)

    subclass_constraint_obj = WithSubclassTypeConstraint(SomeDatatypeClass())
    self.assertEqual('asdf', subclass_constraint_obj.some_value.something())
    self.assertEqual(repr(subclass_constraint_obj),
                     "WithSubclassTypeConstraint(some_value=SomeDatatypeClass())")
    self.assertEqual(
      str(subclass_constraint_obj),
      "WithSubclassTypeConstraint(some_value<+SomeBaseClass>=SomeDatatypeClass())")

  def test_mixin_type_construction(self):
    obj_with_mixin = TypedWithMixin(text_type(' asdf '))
    expected_repr = ("TypedWithMixin(val={unicode_literal}' asdf ')"
                     .format(unicode_literal=self.unicode_literal))
    self.assertEqual(repr(obj_with_mixin), expected_repr)

    expected_str = "TypedWithMixin(val<={}>= asdf )".format(text_type.__name__)
    self.assertEqual(str(obj_with_mixin), expected_str)
    self.assertEqual(obj_with_mixin.as_str(), ' asdf ')
    self.assertEqual(obj_with_mixin.stripped(), 'asdf')

  def test_instance_construction_errors(self):
    # test that kwargs with keywords that aren't field names fail the same way
    expected_rx_str = re.escape(
      """error: in constructor of type SomeTypedDatatype: type check error:
__new__() got an unexpected keyword argument 'something'""")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      SomeTypedDatatype(something=3)

    # not providing all the fields
    expected_msg_ending = (
      "__new__() missing 1 required positional argument: 'val'"
      if PY3 else
      "__new__() takes exactly 2 arguments (1 given)"
    )
    expected_rx_str = re.escape(
      """error: in constructor of type SomeTypedDatatype: type check error:
{}"""
      .format(expected_msg_ending))
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      SomeTypedDatatype()

    # test that too many positional args fails
    expected_msg_ending = (
      "__new__() takes 2 positional arguments but 3 were given"
      if PY3 else
      "__new__() takes exactly 2 arguments (3 given)"
    )
    expected_rx_str = re.escape(
      "error: in constructor of type SomeTypedDatatype: type check error:\n{}"
      .format(expected_msg_ending))
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      SomeTypedDatatype(3, 4)

    expected_rx_str = re.escape(
      """error: in constructor of type CamelCaseWrapper: type check error:
field 'nonneg_int' was invalid: value 3 (with type 'int') must satisfy this type constraint: Exactly(NonNegativeInt).""")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      CamelCaseWrapper(nonneg_int=3)

    # test that kwargs with keywords that aren't field names fail the same way
    expected_rx_str = re.escape(
      "error: in constructor of type CamelCaseWrapper: type check error:\n__new__() got an unexpected keyword argument 'a'")
    with self.assertRaisesRegexp(TypeError, expected_rx_str):
      CamelCaseWrapper(4, a=3)

  def test_type_check_errors(self):
    # single type checking failure
    expected_rx_str = re.escape(
      """error: in constructor of type SomeTypedDatatype: type check error:
field 'val' was invalid: value [] (with type 'list') must satisfy this type constraint: Exactly(int).""")
    with self.assertRaisesRegexp(TypeError, expected_rx_str):
      SomeTypedDatatype([])

    # type checking failure with multiple arguments (one is correct)
    expected_rx_str = re.escape(
      """error: in constructor of type AnotherTypedDatatype: type check error:
field 'elements' was invalid: value {unicode_literal}'should be list' (with type '{type_name}') must satisfy this type constraint: Exactly(list)."""
      .format(type_name=text_type.__name__, unicode_literal=self.unicode_literal))
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      AnotherTypedDatatype(text_type('correct'), text_type('should be list'))

    # type checking failure on both arguments
    expected_rx_str = re.escape(
      """error: in constructor of type AnotherTypedDatatype: type check error:
field 'string' was invalid: value 3 (with type 'int') must satisfy this type constraint: Exactly({type_name}).
field 'elements' was invalid: value {unicode_literal}'should be list' (with type '{type_name}') must satisfy this type constraint: Exactly(list)."""
      .format(type_name=text_type.__name__, unicode_literal=self.unicode_literal))
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      AnotherTypedDatatype(3, text_type('should be list'))

    expected_rx_str = re.escape(
      """error: in constructor of type NonNegativeInt: type check error:
field 'an_int' was invalid: value {unicode_literal}'asdf' (with type '{type_name}') must satisfy this type constraint: Exactly(int)."""
      .format(type_name=text_type.__name__, unicode_literal=self.unicode_literal))
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      NonNegativeInt(text_type('asdf'))

    expected_rx_str = re.escape(
      """error: in constructor of type NonNegativeInt: type check error:
value is negative: -3.""")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      NonNegativeInt(-3)

    expected_rx_str = re.escape(
      """error: in constructor of type WithSubclassTypeConstraint: type check error:
field 'some_value' was invalid: value 3 (with type 'int') must satisfy this type constraint: SubclassesOf(SomeBaseClass).""")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      WithSubclassTypeConstraint(3)

  def test_copy(self):
    obj = AnotherTypedDatatype(string='some_string', elements=[1, 2, 3])
    new_obj = obj.copy(string='another_string')

    self.assertEqual(type(obj), type(new_obj))
    self.assertEqual(new_obj.string, 'another_string')
    self.assertEqual(new_obj.elements, obj.elements)

  def test_copy_failure(self):
    obj = AnotherTypedDatatype(string='some string', elements=[1,2,3])

    expected_rx_str = re.escape(
      """error: in constructor of type AnotherTypedDatatype: type check error:
Replacing fields {'nonexistent_field': 3} of object AnotherTypedDatatype(string=u'some string', elements=[1, 2, 3]) failed:
Field 'nonexistent_field' was not recognized.""")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      obj.copy(nonexistent_field=3)

    expected_msg_ending = (
      "copy() takes 1 positional argument but 2 were given"
      if PY3 else
      "copy() takes exactly 1 argument (2 given)"
    )
    with self.assertRaisesRegexp(TypeError, re.escape(expected_msg_ending)):
      obj.copy(3)

    expected_rx_str = re.escape(
      """error: in constructor of type AnotherTypedDatatype: type check error:
Replacing fields {'elements': 3} of object AnotherTypedDatatype(string=u'some string', elements=[1, 2, 3]) failed:
Type error for field 'elements': value 3 (with type 'int') must satisfy this type constraint: Exactly(list).""")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_str):
      obj.copy(elements=3)

  def test_enum_class_creation_errors(self):
    expected_rx = re.escape(
      "When converting all_values ([1, 2, 3, 1]) to a set, at least one duplicate "
      "was detected. The unique elements of all_values were: OrderedSet([1, 2, 3]).")
    with self.assertRaisesRegexp(ValueError, expected_rx):
      class DuplicateAllowedValues(enum('x', [1, 2, 3, 1])): pass

  def test_enum_instance_creation(self):
    self.assertEqual(1, SomeEnum.create().x)
    self.assertEqual(2, SomeEnum.create(2).x)
    self.assertEqual(1, SomeEnum(1).x)
    self.assertEqual(2, SomeEnum(x=2).x)

  def test_enum_instance_creation_errors(self):
    expected_rx = re.escape(
      "Value 3 for 'x' must be one of: OrderedSet([1, 2]).")
    with self.assertRaisesRegexp(TypeCheckError, expected_rx):
      SomeEnum.create(3)
    with self.assertRaisesRegexp(TypeCheckError, expected_rx):
      SomeEnum(3)
    with self.assertRaisesRegexp(TypeCheckError, expected_rx):
      SomeEnum(x=3)

    expected_rx_falsy_value = re.escape(
      "Value {unicode_literal}'' for 'x' must be one of: OrderedSet([1, 2])."
      .format(unicode_literal=self.unicode_literal))
    with self.assertRaisesRegexp(TypeCheckError, expected_rx_falsy_value):
      SomeEnum(x='')
