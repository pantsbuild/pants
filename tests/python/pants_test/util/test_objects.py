# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import copy
import pickle
from abc import abstractmethod
from textwrap import dedent

from pants.util.objects import (
  Exactly,
  HashableTypedCollection,
  SubclassesOf,
  SuperclassesOf,
  TypeCheckError,
  TypeConstraintError,
  TypedCollection,
  TypedDatatypeInstanceConstructionError,
  datatype,
)
from pants_test.test_base import TestBase


class TypeConstraintTestBase(TestBase):
  class A:

    def __repr__(self):
      return '{}()'.format(type(self).__name__)

    def __str__(self):
      return '(str form): {}'.format(repr(self))

    def __eq__(self, other):
      return type(self) == type(other)

  class B(A):
    pass

  class C(B):
    pass

  class BPrime(A):
    pass


class SuperclassesOfTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaisesWithMessage(ValueError, 'Must supply at least one type'):
      SubclassesOf()

  def test_str_and_repr(self):
    superclasses_of_b = SuperclassesOf(self.B)
    self.assertEqual("SuperclassesOf(B)", str(superclasses_of_b))
    self.assertEqual("SuperclassesOf(B)", repr(superclasses_of_b))

    superclasses_of_multiple = SuperclassesOf(self.A, self.B)
    self.assertEqual("SuperclassesOf(A or B)", str(superclasses_of_multiple))
    self.assertEqual("SuperclassesOf(A, B)", repr(superclasses_of_multiple))

  def test_single(self):
    superclasses_of_b = SuperclassesOf(self.B)
    self.assertTrue(superclasses_of_b.satisfied_by(self.A()))
    self.assertTrue(superclasses_of_b.satisfied_by(self.B()))
    self.assertFalse(superclasses_of_b.satisfied_by(self.BPrime()))
    self.assertFalse(superclasses_of_b.satisfied_by(self.C()))

  def test_multiple(self):
    superclasses_of_a_or_b = SuperclassesOf(self.A, self.B)
    self.assertTrue(superclasses_of_a_or_b.satisfied_by(self.A()))
    self.assertTrue(superclasses_of_a_or_b.satisfied_by(self.B()))
    self.assertFalse(superclasses_of_a_or_b.satisfied_by(self.BPrime()))
    self.assertFalse(superclasses_of_a_or_b.satisfied_by(self.C()))

  def test_validate(self):
    superclasses_of_a_or_b = SuperclassesOf(self.A, self.B)
    self.assertEqual(self.A(), superclasses_of_a_or_b.validate_satisfied_by(self.A()))
    self.assertEqual(self.B(), superclasses_of_a_or_b.validate_satisfied_by(self.B()))
    with self.assertRaisesWithMessage(
        TypeConstraintError,
        "value C() (with type 'C') must satisfy this type constraint: SuperclassesOf(A or B)."):
      superclasses_of_a_or_b.validate_satisfied_by(self.C())


class ExactlyTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaisesWithMessage(ValueError, 'Must supply at least one type'):
      Exactly()

  def test_single(self):
    exactly_b = Exactly(self.B)
    self.assertFalse(exactly_b.satisfied_by(self.A()))
    self.assertTrue(exactly_b.satisfied_by(self.B()))
    self.assertFalse(exactly_b.satisfied_by(self.BPrime()))
    self.assertFalse(exactly_b.satisfied_by(self.C()))

  def test_multiple(self):
    exactly_a_or_b = Exactly(self.A, self.B)
    self.assertTrue(exactly_a_or_b.satisfied_by(self.A()))
    self.assertTrue(exactly_a_or_b.satisfied_by(self.B()))
    self.assertFalse(exactly_a_or_b.satisfied_by(self.BPrime()))
    self.assertFalse(exactly_a_or_b.satisfied_by(self.C()))

  def test_disallows_unsplatted_lists(self):
    with self.assertRaisesWithMessage(TypeError,
                                                'Supplied types must be types. ([1],)'):
      Exactly([1])

  def test_str_and_repr(self):
    exactly_b = Exactly(self.B)
    self.assertEqual("Exactly(B)", str(exactly_b))
    self.assertEqual("Exactly(B)", repr(exactly_b))

    exactly_multiple = Exactly(self.A, self.B)
    self.assertEqual("Exactly(A or B)", str(exactly_multiple))
    self.assertEqual("Exactly(A, B)", repr(exactly_multiple))

  def test_checking_via_bare_type(self):
    self.assertTrue(Exactly(self.B).satisfied_by_type(self.B))
    self.assertFalse(Exactly(self.B).satisfied_by_type(self.C))

  def test_validate(self):
    exactly_a_or_b = Exactly(self.A, self.B)
    self.assertEqual(self.A(), exactly_a_or_b.validate_satisfied_by(self.A()))
    self.assertEqual(self.B(), exactly_a_or_b.validate_satisfied_by(self.B()))
    with self.assertRaisesWithMessage(
        TypeConstraintError,
        "value C() (with type 'C') must satisfy this type constraint: Exactly(A or B)."):
      exactly_a_or_b.validate_satisfied_by(self.C())


class SubclassesOfTest(TypeConstraintTestBase):
  def test_none(self):
    with self.assertRaisesWithMessage(ValueError, 'Must supply at least one type'):
      SubclassesOf()

  def test_str_and_repr(self):
    subclasses_of_b = SubclassesOf(self.B)
    self.assertEqual("SubclassesOf(B)", str(subclasses_of_b))
    self.assertEqual("SubclassesOf(B)", repr(subclasses_of_b))

    subclasses_of_multiple = SubclassesOf(self.A, self.B)
    self.assertEqual("SubclassesOf(A or B)", str(subclasses_of_multiple))
    self.assertEqual("SubclassesOf(A, B)", repr(subclasses_of_multiple))

  def test_single(self):
    subclasses_of_b = SubclassesOf(self.B)
    self.assertFalse(subclasses_of_b.satisfied_by(self.A()))
    self.assertTrue(subclasses_of_b.satisfied_by(self.B()))
    self.assertFalse(subclasses_of_b.satisfied_by(self.BPrime()))
    self.assertTrue(subclasses_of_b.satisfied_by(self.C()))

  def test_multiple(self):
    subclasses_of_b_or_c = SubclassesOf(self.B, self.C)
    self.assertTrue(subclasses_of_b_or_c.satisfied_by(self.B()))
    self.assertTrue(subclasses_of_b_or_c.satisfied_by(self.C()))
    self.assertFalse(subclasses_of_b_or_c.satisfied_by(self.BPrime()))
    self.assertFalse(subclasses_of_b_or_c.satisfied_by(self.A()))

  def test_validate(self):
    subclasses_of_a_or_b = SubclassesOf(self.A, self.B)
    self.assertEqual(self.A(), subclasses_of_a_or_b.validate_satisfied_by(self.A()))
    self.assertEqual(self.B(), subclasses_of_a_or_b.validate_satisfied_by(self.B()))
    self.assertEqual(self.C(), subclasses_of_a_or_b.validate_satisfied_by(self.C()))
    with self.assertRaisesWithMessage(
        TypeConstraintError,
        "value 1 (with type 'int') must satisfy this type constraint: SubclassesOf(A or B)."):
      subclasses_of_a_or_b.validate_satisfied_by(1)


class TypedCollectionTest(TypeConstraintTestBase):
  def test_str_and_repr(self):
    collection_of_exactly_b = TypedCollection(Exactly(self.B))
    self.assertEqual("TypedCollection(Exactly(B))", str(collection_of_exactly_b))
    self.assertEqual("TypedCollection(Exactly(B))", repr(collection_of_exactly_b))

    collection_of_multiple_subclasses = TypedCollection(
      SubclassesOf(self.A, self.B))
    self.assertEqual("TypedCollection(SubclassesOf(A or B))",
                     str(collection_of_multiple_subclasses))
    self.assertEqual("TypedCollection(SubclassesOf(A, B))",
                     repr(collection_of_multiple_subclasses))

  def test_collection_single(self):
    collection_constraint = TypedCollection(Exactly(self.A))
    self.assertTrue(collection_constraint.satisfied_by([self.A()]))
    self.assertFalse(collection_constraint.satisfied_by([self.A(), self.B()]))
    self.assertTrue(collection_constraint.satisfied_by([self.A(), self.A()]))

  def test_collection_multiple(self):
    collection_constraint = TypedCollection(SubclassesOf(self.B, self.BPrime))
    self.assertTrue(collection_constraint.satisfied_by([self.B(), self.C(), self.BPrime()]))
    self.assertFalse(collection_constraint.satisfied_by([self.B(), self.A()]))

  def test_no_complex_sub_constraint(self):
    sub_collection = TypedCollection(Exactly(self.A))
    with self.assertRaisesWithMessage(
        TypeError,
        "constraint for collection must be a TypeOnlyConstraint! was: {}".format(sub_collection)):
      TypedCollection(sub_collection)

  def test_validate(self):
    collection_exactly_a_or_b = TypedCollection(Exactly(self.A, self.B))
    self.assertEqual([self.A()], collection_exactly_a_or_b.validate_satisfied_by([self.A()]))
    self.assertEqual([self.B()], collection_exactly_a_or_b.validate_satisfied_by([self.B()]))
    with self.assertRaisesWithMessage(TypeConstraintError, dedent("""\
        in wrapped constraint TypedCollection(Exactly(A or B)): value A() (with type 'A') must satisfy this type constraint: SubclassesOf(Iterable).
        Note that objects matching {} are not considered iterable.""")
                                      .format(TypedCollection.exclude_iterable_constraint)):
      collection_exactly_a_or_b.validate_satisfied_by(self.A())
    with self.assertRaisesWithMessage(TypeConstraintError, dedent("""\
        in wrapped constraint TypedCollection(Exactly(A or B)) matching iterable object [C()]: value C() (with type 'C') must satisfy this type constraint: Exactly(A or B).""")):
      collection_exactly_a_or_b.validate_satisfied_by([self.C()])

  def test_iterable_detection(self):
    class StringCollectionField(datatype([('hello_strings', TypedCollection(Exactly(str)))])):
      pass

    self.assertEqual(['xxx'], StringCollectionField(hello_strings=['xxx']).hello_strings)

    with self.assertRaisesWithMessage(TypeCheckError, dedent("""\
        type check error in class StringCollectionField: 1 error type checking constructor arguments:
        field 'hello_strings' was invalid: in wrapped constraint TypedCollection(Exactly(str)): value 'xxx' (with type 'str') must satisfy this type constraint: SubclassesOf(Iterable).
        Note that objects matching {exclude_constraint} are not considered iterable.""")
                                      .format(exclude_constraint=TypedCollection.exclude_iterable_constraint)):
      StringCollectionField(hello_strings='xxx')

  def test_hashable_collection(self):
    class NormalCollection(datatype(['value'])):
      pass

    with self.assertRaisesWithMessage(
        TypeError,
        "For datatype object NormalCollection(value=[]) (type 'NormalCollection'): in field 'value': unhashable type: 'list'"):
      hash(NormalCollection([]))

    class HashableIntVector(datatype([('value', HashableTypedCollection(Exactly(int)))])):
      pass

    vec = HashableIntVector((1, 2, 3,))
    self.assertEqual(vec.value, (1, 2, 3,))
    self.assertIsInstance(hash(vec), int)


class ExportedDatatype(datatype(['val'])):
  pass


class AbsClass:
  pass


class SomeTypedDatatype(datatype([('val', int)])): pass


class SomeMixin:

  @abstractmethod
  def as_str(self): pass

  def stripped(self):
    return self.as_str().strip()


class TypedWithMixin(datatype([('val', str)]), SomeMixin):
  """Example of using `datatype()` with a mixin."""

  def as_str(self):
    return self.val


class AnotherTypedDatatype(datatype([('string', str), ('elements', list)])): pass


class WithExplicitTypeConstraint(datatype([('a_string', str), ('an_int', Exactly(int))])): pass


class MixedTyping(datatype(['value', ('name', str)])): pass


class SomeBaseClass:
  @abstractmethod
  def something(self): pass


class SomeDatatypeClass(SomeBaseClass):
  def something(self):
    return 'asdf'

  def __repr__(self):
    return 'SomeDatatypeClass()'


class WithSubclassTypeConstraint(datatype([('some_value', SubclassesOf(SomeBaseClass))])): pass


class WithCollectionTypeConstraint(datatype([
    ('dependencies', TypedCollection(Exactly(int))),
])):
  pass


class NonNegativeInt(datatype([('an_int', int)])):
  """Example of overriding __new__() to perform deeper argument checking."""

  # NB: __new__() in the class returned by datatype() will raise if any kwargs are provided, but
  # subclasses are free to pass around kwargs as long as they don't forward them to that particular
  # __new__() method.
  def __new__(cls, *args, **kwargs):
    # Call the superclass ctor first to ensure the type is correct.
    this_object = super().__new__(cls, *args, **kwargs)

    value = this_object.an_int

    if value < 0:
      raise cls.make_type_error("value is negative: {!r}.".format(value))

    return this_object


class CamelCaseWrapper(datatype([('nonneg_int', NonNegativeInt)])): pass


class ReturnsNotImplemented:
  def __eq__(self, other):
    return NotImplemented


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
    with self.assertRaisesWithMessageContaining(TypeError, 'datatype object is not iterable'):
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
    with self.assertRaisesWithMessage(AttributeError, "can't set attribute"):
      bar_inst.val = 2

  def test_invalid_field_name(self):
    with self.assertRaisesWithMessage(
        ValueError,
        "Type names and field names must be valid identifiers: '0isntanallowedfirstchar'"):
      datatype(['0isntanallowedfirstchar'])
    with self.assertRaisesWithMessage(
        ValueError,
        "Field names cannot start with an underscore: '_no_leading_underscore'"):
      datatype(['_no_leading_underscore'])

  def test_override_eq_disallowed(self):
    class OverridesEq(datatype(['myval'])):
      def __eq__(self, other):
        return other.myval == self.myval
    with self.assertRaisesWithMessage(TypeCheckError, 'type check error in class OverridesEq: Should not override __eq__.'):
      OverridesEq(1)

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
    with self.assertRaisesWithMessageContaining(TypeError, "__new__() got multiple values for argument 'val'"):
      bar(1, val=1)

  def test_too_many_args(self):
    bar = datatype(['val', 'zal'])
    with self.assertRaisesWithMessageContaining(
        TypeError,
        '__new__() takes 3 positional arguments but 4 were given'):
      bar(1, 1, 1)

  def test_unexpect_kwarg(self):
    bar = datatype(['val'])
    with self.assertRaisesWithMessageContaining(
        TypeError,
        "__new__() got an unexpected keyword argument 'other'"):
      bar(other=1)


class TypedDatatypeTest(TestBase):

  def test_class_construction_errors(self):
    # NB: datatype subclasses declared at top level are the success cases
    # here by not failing on import.

    # If the type_name can't be converted into a suitable identifier, throw a
    # ValueError.
    expected_msg = "Type names and field names must be valid identifiers: \"<class 'int'>\""
    with self.assertRaisesWithMessage(ValueError, expected_msg):
      class NonStrType(datatype([int])): pass

    # This raises a TypeError because it doesn't provide a required argument.
    expected_msg = "datatype() missing 1 required positional argument: 'field_decls'"
    with self.assertRaisesWithMessage(TypeError, expected_msg):
      class NoFields(datatype()): pass

    expected_msg = "Type names and field names must be valid identifiers: \"<class 'str'>\""
    with self.assertRaisesWithMessage(ValueError, expected_msg):
      class JustTypeField(datatype([str])): pass

    expected_msg = "Type names and field names must be valid identifiers: '3'"
    with self.assertRaisesWithMessage(ValueError, expected_msg):
      class NonStringField(datatype([3])): pass

    expected_msg = "Type names and field names must be valid identifiers: '32'"
    with self.assertRaisesWithMessage(ValueError, expected_msg):
      class NonStringTypeField(datatype([(32, int)])): pass

    expected_msg = "Encountered duplicate field name: 'field_a'"
    with self.assertRaisesWithMessage(ValueError, expected_msg):
      class MultipleSameName(datatype([
          'field_a',
          'field_b',
          'field_a',
      ])):
        pass

    expected_msg = "Encountered duplicate field name: 'field_a'"
    with self.assertRaisesWithMessage(ValueError, expected_msg):
      class MultipleSameNameWithType(datatype([
            'field_a',
            ('field_a', int),
          ])):
        pass

    expected_msg = (
      "type spec for field 'a_field' was not a type or TypeConstraint: "
      "was 2 (type 'int').")
    with self.assertRaisesWithMessage(TypeError, expected_msg):
      class InvalidTypeSpec(datatype([('a_field', 2)])): pass

  def test_instance_construction_by_repr(self):
    some_val = SomeTypedDatatype(3)
    self.assertEqual(3, some_val.val)
    self.assertEqual(repr(some_val), "SomeTypedDatatype(val=3)")
    self.assertEqual(str(some_val), "SomeTypedDatatype(val<Exactly(int)>=3)")

    some_object = WithExplicitTypeConstraint('asdf', 45)
    self.assertEqual(some_object.a_string, 'asdf')
    self.assertEqual(some_object.an_int, 45)
    self.assertEqual(str(some_object), "WithExplicitTypeConstraint(a_string<Exactly(str)>=asdf, an_int<Exactly(int)>=45)")
    self.assertEqual(repr(some_object), "WithExplicitTypeConstraint(a_string='asdf', an_int=45)")

    some_nonneg_int = NonNegativeInt(an_int=3)
    self.assertEqual(3, some_nonneg_int.an_int)
    self.assertEqual(repr(some_nonneg_int), "NonNegativeInt(an_int=3)")
    self.assertEqual(str(some_nonneg_int), "NonNegativeInt(an_int<Exactly(int)>=3)")

    wrapped_nonneg_int = CamelCaseWrapper(NonNegativeInt(45))
    # test attribute naming for camel-cased types
    self.assertEqual(45, wrapped_nonneg_int.nonneg_int.an_int)
    # test that repr() is called inside repr(), and str() inside str()
    self.assertEqual(repr(wrapped_nonneg_int),
                     "CamelCaseWrapper(nonneg_int=NonNegativeInt(an_int=45))")
    self.assertEqual(
      str(wrapped_nonneg_int),
      "CamelCaseWrapper(nonneg_int<Exactly(NonNegativeInt)>=NonNegativeInt(an_int<Exactly(int)>=45))")

    mixed_type_obj = MixedTyping(value=3, name='asdf')
    self.assertEqual(3, mixed_type_obj.value)
    self.assertEqual(repr(mixed_type_obj), "MixedTyping(value=3, name='asdf')")
    self.assertEqual(str(mixed_type_obj), "MixedTyping(value=3, name<Exactly(str)>=asdf)")

    subclass_constraint_obj = WithSubclassTypeConstraint(SomeDatatypeClass())
    self.assertEqual('asdf', subclass_constraint_obj.some_value.something())
    self.assertEqual(repr(subclass_constraint_obj),
                     "WithSubclassTypeConstraint(some_value=SomeDatatypeClass())")
    self.assertEqual(
      str(subclass_constraint_obj),
      "WithSubclassTypeConstraint(some_value<SubclassesOf(SomeBaseClass)>=SomeDatatypeClass())")

  def test_mixin_type_construction(self):
    obj_with_mixin = TypedWithMixin(' asdf ')
    self.assertEqual(repr(obj_with_mixin), "TypedWithMixin(val=' asdf ')")
    self.assertEqual(str(obj_with_mixin), "TypedWithMixin(val<Exactly(str)>= asdf )")
    self.assertEqual(obj_with_mixin.as_str(), ' asdf ')
    self.assertEqual(obj_with_mixin.stripped(), 'asdf')

  def test_instance_with_collection_construction_str_repr(self):
    # TODO: convert the type of the input collection using a `wrapper_type` argument!
    obj_with_collection = WithCollectionTypeConstraint([3])
    self.assertEqual("WithCollectionTypeConstraint(dependencies<TypedCollection(Exactly(int))>=[3])",
                     str(obj_with_collection))
    self.assertEqual("WithCollectionTypeConstraint(dependencies=[3])",
                     repr(obj_with_collection))

  def test_instance_construction_errors(self):
    expected_msg = "type check error in class SomeTypedDatatype: error in namedtuple() base constructor: __new__() got an unexpected keyword argument 'something'"
    with self.assertRaisesWithMessage(TypeError, expected_msg):
      SomeTypedDatatype(something=3)

    # not providing all the fields
    expected_msg = "type check error in class SomeTypedDatatype: error in namedtuple() base constructor: __new__() missing 1 required positional argument: 'val'"
    with self.assertRaisesWithMessage(TypeError, expected_msg):
      SomeTypedDatatype()

    # unrecognized fields
    expected_msg = "type check error in class SomeTypedDatatype: error in namedtuple() base constructor: __new__() takes 2 positional arguments but 3 were given"
    with self.assertRaisesWithMessage(TypeError, expected_msg):
      SomeTypedDatatype(3, 4)

    expected_msg = (
      """type check error in class CamelCaseWrapper: 1 error type checking constructor arguments:
field 'nonneg_int' was invalid: value 3 (with type 'int') must satisfy this type constraint: Exactly(NonNegativeInt).""")
    with self.assertRaisesWithMessage(TypedDatatypeInstanceConstructionError,
                                                expected_msg):
      CamelCaseWrapper(nonneg_int=3)

    # test that kwargs with keywords that aren't field names fail the same way
    expected_msg = "type check error in class CamelCaseWrapper: error in namedtuple() base constructor: __new__() got an unexpected keyword argument 'a'"
    with self.assertRaisesWithMessage(TypeError, expected_msg):
      CamelCaseWrapper(4, a=3)

  def test_type_check_errors(self):
    self.maxDiff = None

    # single type checking failure
    expected_msg = (
      """type check error in class SomeTypedDatatype: 1 error type checking constructor arguments:
field 'val' was invalid: value [] (with type 'list') must satisfy this type constraint: Exactly(int).""")
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      SomeTypedDatatype([])

    # type checking failure with multiple arguments (one is correct)
    expected_msg = (
      """type check error in class AnotherTypedDatatype: 1 error type checking constructor arguments:
field 'elements' was invalid: value 'should be list' (with type 'str') must satisfy this type constraint: Exactly(list).""")
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      AnotherTypedDatatype('correct', 'should be list')

    # type checking failure on both arguments
    expected_msg = (
        """type check error in class AnotherTypedDatatype: 2 errors type checking constructor arguments:
field 'string' was invalid: value 3 (with type 'int') must satisfy this type constraint: Exactly(str).
field 'elements' was invalid: value 'should be list' (with type 'str') must satisfy this type constraint: Exactly(list).""")
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      AnotherTypedDatatype(3, 'should be list')

    expected_msg = (
        """type check error in class NonNegativeInt: 1 error type checking constructor arguments:
field 'an_int' was invalid: value 'asdf' (with type 'str') must satisfy this type constraint: Exactly(int).""")
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      NonNegativeInt('asdf')

    expected_msg = "type check error in class NonNegativeInt: value is negative: -3."
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      NonNegativeInt(-3)

    expected_msg = (
      """type check error in class WithSubclassTypeConstraint: 1 error type checking constructor arguments:
field 'some_value' was invalid: value 3 (with type 'int') must satisfy this type constraint: SubclassesOf(SomeBaseClass).""")
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      WithSubclassTypeConstraint(3)

    expected_msg = """\
type check error in class WithCollectionTypeConstraint: 1 error type checking constructor arguments:
field 'dependencies' was invalid: in wrapped constraint TypedCollection(Exactly(int)): value 3 (with type 'int') must satisfy this type constraint: SubclassesOf(Iterable).
Note that objects matching {} are not considered iterable.""".format(TypedCollection.exclude_iterable_constraint)
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      WithCollectionTypeConstraint(3)

    expected_msg = ("""\
type check error in class WithCollectionTypeConstraint: 1 error type checking constructor arguments:
field 'dependencies' was invalid: in wrapped constraint TypedCollection(Exactly(int)) matching iterable object [3, 'asdf']: value 'asdf' (with type 'str') must satisfy this type constraint: Exactly(int).""")
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      WithCollectionTypeConstraint([3, "asdf"])

  def test_copy(self):
    obj = AnotherTypedDatatype(string='some_string', elements=[1, 2, 3])
    new_obj = obj.copy(string='another_string')

    self.assertEqual(type(obj), type(new_obj))
    self.assertEqual(new_obj.string, 'another_string')
    self.assertEqual(new_obj.elements, obj.elements)

  def test_copy_failure(self):
    obj = AnotherTypedDatatype(string='some string', elements=[1,2,3])

    expected_msg = (
      """type check error in class AnotherTypedDatatype: error in namedtuple() base constructor: __new__() got an unexpected keyword argument 'nonexistent_field'""")
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      obj.copy(nonexistent_field=3)

    expected_msg = (
      """type check error in class AnotherTypedDatatype: 1 error type checking constructor arguments:
field 'elements' was invalid: value 3 (with type 'int') must satisfy this type constraint: Exactly(list).""")
    with self.assertRaisesWithMessage(TypeCheckError, expected_msg):
      obj.copy(elements=3)
