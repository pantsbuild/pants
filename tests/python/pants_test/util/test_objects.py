# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import pickle
from abc import abstractmethod
from builtins import object, str

from future.utils import PY2, PY3, text_type

from pants.util.objects import (Exactly, SubclassesOf, SuperclassesOf, TypeCheckError,
                                TypedDatatypeInstanceConstructionError, datatype)
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


class TypedWithMixin(datatype([('val', text_type)]), SomeMixin):
  """Example of using `datatype()` with a mixin."""

  def as_str(self):
    return self.val


class AnotherTypedDatatype(datatype([('string', text_type), ('elements', list)])): pass


class WithExplicitTypeConstraint(datatype([('a_string', text_type), ('an_int', Exactly(int))])): pass


class MixedTyping(datatype(['value', ('name', text_type)])): pass


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


class DatatypeTest(BaseTest):

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


class TypedDatatypeTest(BaseTest):

  def test_class_construction_errors(self):
    # NB: datatype subclasses declared at top level are the success cases
    # here by not failing on import.

    # If the type_name can't be converted into a suitable identifier, throw a
    # ValueError.
    with self.assertRaises(ValueError) as cm:
      class NonStrType(datatype([int])): pass
    expected_msg = (
      "Type names and field names must be valid identifiers: \"<class 'int'>\""
      if PY3 else
      "Type names and field names can only contain alphanumeric characters and underscores: \"<type 'int'>\""
    )
    self.assertEqual(str(cm.exception), expected_msg)

    # This raises a TypeError because it doesn't provide a required argument.
    with self.assertRaises(TypeError) as cm:
      class NoFields(datatype()): pass
    expected_msg = (
      "datatype() missing 1 required positional argument: 'field_decls'"
      if PY3 else
      "datatype() takes at least 1 argument (0 given)"
    )
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(ValueError) as cm:
      class JustTypeField(datatype([text_type])): pass
    expected_msg = (
      "Type names and field names must be valid identifiers: \"<class 'str'>\""
      if PY3 else
      "Type names and field names can only contain alphanumeric characters and underscores: \"<type 'unicode'>\""
    )
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(ValueError) as cm:
      class NonStringField(datatype([3])): pass
    expected_msg = (
      "Type names and field names must be valid identifiers: '3'"
      if PY3 else
      "Type names and field names cannot start with a number: '3'"
    )
    self.assertEqual(str(cm.exception), expected_msg)

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

    with self.assertRaises(TypeError) as cm:
      class InvalidTypeSpec(datatype([('a_field', 2)])): pass
    expected_msg = (
      "type spec for field 'a_field' was not a type or TypeConstraint: "
      "was 2 (type 'int').")
    self.assertEqual(str(cm.exception), expected_msg)

  def test_instance_construction_by_repr(self):
    some_val = SomeTypedDatatype(3)
    self.assertEqual(3, some_val.val)
    self.assertEqual(repr(some_val), "SomeTypedDatatype(val=3)")
    self.assertEqual(str(some_val), "SomeTypedDatatype(val<=int>=3)")

    some_object = WithExplicitTypeConstraint(text_type('asdf'), 45)
    self.assertEqual(some_object.a_string, 'asdf')
    self.assertEqual(some_object.an_int, 45)
    def compare_repr(include_unicode = False):
      expected_message = "WithExplicitTypeConstraint(a_string={unicode_literal}'asdf', an_int=45)"\
        .format(unicode_literal='u' if include_unicode else '')
      self.assertEqual(repr(some_object), expected_message)
    def compare_str(unicode_type_name):
      expected_message = "WithExplicitTypeConstraint(a_string<={}>=asdf, an_int<=int>=45)".format(unicode_type_name)
      self.assertEqual(str(some_object), expected_message)
    if PY2:
      compare_str('unicode')
      compare_repr(include_unicode=True)
    else:
      compare_str('str')
      compare_repr()

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
    def compare_repr(include_unicode = False):
      expected_message = "MixedTyping(value=3, name={unicode_literal}'asdf')" \
        .format(unicode_literal='u' if include_unicode else '')
      self.assertEqual(repr(mixed_type_obj), expected_message)
    def compare_str(unicode_type_name):
      expected_message = "MixedTyping(value=3, name<={}>=asdf)".format(unicode_type_name)
      self.assertEqual(str(mixed_type_obj), expected_message)
    if PY2:
      compare_str('unicode')
      compare_repr(include_unicode=True)
    else:
      compare_str('str')
      compare_repr()

    subclass_constraint_obj = WithSubclassTypeConstraint(SomeDatatypeClass())
    self.assertEqual('asdf', subclass_constraint_obj.some_value.something())
    self.assertEqual(repr(subclass_constraint_obj),
                     "WithSubclassTypeConstraint(some_value=SomeDatatypeClass())")
    self.assertEqual(
      str(subclass_constraint_obj),
      "WithSubclassTypeConstraint(some_value<+SomeBaseClass>=SomeDatatypeClass())")

  def test_mixin_type_construction(self):
    obj_with_mixin = TypedWithMixin(text_type(' asdf '))
    def compare_repr(include_unicode = False):
      expected_message = "TypedWithMixin(val={unicode_literal}' asdf ')" \
        .format(unicode_literal='u' if include_unicode else '')
      self.assertEqual(repr(obj_with_mixin), expected_message)
    def compare_str(unicode_type_name):
      expected_message = "TypedWithMixin(val<={}>= asdf )".format(unicode_type_name)
      self.assertEqual(str(obj_with_mixin), expected_message)
    if PY2:
      compare_str('unicode')
      compare_repr(include_unicode=True)
    else:
      compare_str('str')
      compare_repr()
    self.assertEqual(obj_with_mixin.as_str(), ' asdf ')
    self.assertEqual(obj_with_mixin.stripped(), 'asdf')

  def test_instance_construction_errors(self):
    with self.assertRaises(TypeError) as cm:
      SomeTypedDatatype(something=3)
    expected_msg = "error: in constructor of type SomeTypedDatatype: type check error:\n__new__() got an unexpected keyword argument 'something'"
    self.assertEqual(str(cm.exception), expected_msg)

    # not providing all the fields
    with self.assertRaises(TypeError) as cm:
      SomeTypedDatatype()
    expected_msg_ending = (
      "__new__() missing 1 required positional argument: 'val'"
      if PY3 else
      "__new__() takes exactly 2 arguments (1 given)"
    )
    expected_msg = "error: in constructor of type SomeTypedDatatype: type check error:\n" + expected_msg_ending
    self.assertEqual(str(cm.exception), expected_msg)

    # unrecognized fields
    with self.assertRaises(TypeError) as cm:
      SomeTypedDatatype(3, 4)
    expected_msg_ending = (
      "__new__() takes 2 positional arguments but 3 were given"
      if PY3 else
      "__new__() takes exactly 2 arguments (3 given)"
    )
    expected_msg = "error: in constructor of type SomeTypedDatatype: type check error:\n" + expected_msg_ending
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(TypedDatatypeInstanceConstructionError) as cm:
      CamelCaseWrapper(nonneg_int=3)
    expected_msg = (
      """error: in constructor of type CamelCaseWrapper: type check error:
field 'nonneg_int' was invalid: value 3 (with type 'int') must satisfy this type constraint: Exactly(NonNegativeInt).""")
    self.assertEqual(str(cm.exception), expected_msg)

    # test that kwargs with keywords that aren't field names fail the same way
    with self.assertRaises(TypeError) as cm:
      CamelCaseWrapper(4, a=3)
    expected_msg = "error: in constructor of type CamelCaseWrapper: type check error:\n__new__() got an unexpected keyword argument 'a'"
    self.assertEqual(str(cm.exception), expected_msg)

  def test_type_check_errors(self):
    # single type checking failure
    with self.assertRaises(TypeCheckError) as cm:
      SomeTypedDatatype([])
    expected_msg = (
      """error: in constructor of type SomeTypedDatatype: type check error:
field 'val' was invalid: value [] (with type 'list') must satisfy this type constraint: Exactly(int).""")
    self.assertEqual(str(cm.exception), expected_msg)

    # type checking failure with multiple arguments (one is correct)
    with self.assertRaises(TypeCheckError) as cm:
      AnotherTypedDatatype(text_type('correct'), text_type('should be list'))
    def compare_str(unicode_type_name, include_unicode=False):
      expected_message = (
        """error: in constructor of type AnotherTypedDatatype: type check error:
field 'elements' was invalid: value {unicode_literal}'should be list' (with type '{type_name}') must satisfy this type constraint: Exactly(list)."""
      .format(type_name=unicode_type_name, unicode_literal='u' if include_unicode else ''))
      self.assertEqual(str(cm.exception), expected_message)
    if PY2:
      compare_str('unicode', include_unicode=True)
    else:
      compare_str('str')

    # type checking failure on both arguments
    with self.assertRaises(TypeCheckError) as cm:
      AnotherTypedDatatype(3, text_type('should be list'))
    def compare_str(unicode_type_name, include_unicode=False):
      expected_message = (
        """error: in constructor of type AnotherTypedDatatype: type check error:
field 'string' was invalid: value 3 (with type 'int') must satisfy this type constraint: Exactly({type_name}).
field 'elements' was invalid: value {unicode_literal}'should be list' (with type '{type_name}') must satisfy this type constraint: Exactly(list)."""
          .format(type_name=unicode_type_name, unicode_literal='u' if include_unicode else ''))
      self.assertEqual(str(cm.exception), expected_message)
    if PY2:
      compare_str('unicode', include_unicode=True)
    else:
      compare_str('str')

    with self.assertRaises(TypeCheckError) as cm:
      NonNegativeInt(text_type('asdf'))
    def compare_str(unicode_type_name, include_unicode=False):
      expected_message = (
        """error: in constructor of type NonNegativeInt: type check error:
field 'an_int' was invalid: value {unicode_literal}'asdf' (with type '{type_name}') must satisfy this type constraint: Exactly(int)."""
          .format(type_name=unicode_type_name, unicode_literal='u' if include_unicode else ''))
      self.assertEqual(str(cm.exception), expected_message)
    if PY2:
      compare_str('unicode', include_unicode=True)
    else:
      compare_str('str')

    with self.assertRaises(TypeCheckError) as cm:
      NonNegativeInt(-3)
    expected_msg = (
      """error: in constructor of type NonNegativeInt: type check error:
value is negative: -3.""")
    self.assertEqual(str(cm.exception), expected_msg)

    with self.assertRaises(TypeCheckError) as cm:
      WithSubclassTypeConstraint(3)
    expected_msg = (
      """error: in constructor of type WithSubclassTypeConstraint: type check error:
field 'some_value' was invalid: value 3 (with type 'int') must satisfy this type constraint: SubclassesOf(SomeBaseClass).""")
    self.assertEqual(str(cm.exception), expected_msg)
