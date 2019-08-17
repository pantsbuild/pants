# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from abc import ABC, abstractmethod
from collections import OrderedDict, namedtuple
from collections.abc import Iterable

from twitter.common.collections import OrderedSet

from pants.util.memo import memoized_classproperty
from pants.util.meta import classproperty
from pants.util.strutil import pluralize


class TypeCheckError(TypeError):

  # TODO: make some wrapper exception class to make this kind of
  # prefixing easy (maybe using a class field format string?).
  def __init__(self, type_name, msg, *args, **kwargs):
    formatted_msg = f"type check error in class {type_name}: {msg}"
    super().__init__(formatted_msg, *args, **kwargs)


# TODO: remove the `.type_check_error_type` property in `DatatypeMixin` and just have mixers
# override a class object!
class TypedDatatypeInstanceConstructionError(TypeCheckError):
  """Raised when a datatype()'s fields fail a type check upon construction."""


class DatatypeMixin(ABC):
  """Decouple datatype logic from the way it's created to ease migration to python 3 dataclasses."""

  @classproperty
  @abstractmethod
  def type_check_error_type(cls):
    """The exception type to use in make_type_error()."""

  @classmethod
  def make_type_error(cls, msg, *args, **kwargs):
    """A helper method to generate an exception type for type checking errors.

    This method uses `cls.type_check_error_type` to ensure that type checking errors can be caught
    with a reliable exception type. The type returned by `cls.type_check_error_type` should ensure
    that the exception messages are prefixed with enough context to be useful and *not* confusing.
    """
    return cls.type_check_error_type(cls.__name__, msg, *args, **kwargs)

  @abstractmethod
  def copy(self, **kwargs):
    """Return a new object of the same type, replacing specified fields with new values"""


# TODO(#7074): Migrate to python 3 dataclasses!
def datatype(field_decls, superclass_name=None, **kwargs):
  """A wrapper for `namedtuple` that accounts for the type of the object in equality.

  Field declarations can be a string, which declares a field with that name and
  no type checking. Field declarations can also be a tuple `('field_name',
  field_type)`, which declares a field named `field_name` which is type-checked
  at construction. If a type is given, the value provided to the constructor for
  that field must be exactly that type (i.e. `type(x) == field_type`), and not
  e.g. a subclass.

  :param field_decls: Iterable of field declarations.
  :return: A type object which can then be subclassed.
  :raises: :class:`TypeError`
  """
  field_names = []
  fields_with_constraints = OrderedDict()
  for maybe_decl in field_decls:
    # ('field_name', type)
    if isinstance(maybe_decl, tuple):
      field_name, type_spec = maybe_decl
      if isinstance(type_spec, type):
        type_constraint = Exactly(type_spec)
      elif isinstance(type_spec, TypeConstraint):
        type_constraint = type_spec
      else:
        raise TypeError(
          "type spec for field '{}' was not a type or TypeConstraint: was {!r} (type {!r})."
          .format(field_name, type_spec, type(type_spec).__name__))
      fields_with_constraints[field_name] = type_constraint
    else:
      # interpret it as a field name without a type to check
      field_name = maybe_decl
    # namedtuple() already checks field uniqueness
    field_names.append(field_name)

  if not superclass_name:
    superclass_name = '_anonymous_namedtuple_subclass'

  namedtuple_cls = namedtuple(superclass_name, field_names, **kwargs)

  class DataType(namedtuple_cls, DatatypeMixin):
    type_check_error_type = TypedDatatypeInstanceConstructionError

    def __new__(cls, *args, **kwargs):
      # TODO: Ideally we could execute this exactly once per `cls` but it should be a
      # relatively cheap check.
      if not hasattr(cls.__eq__, '_eq_override_canary'):
        raise cls.make_type_error('Should not override __eq__.')

      try:
        this_object = super().__new__(cls, *args, **kwargs)
      except TypeError as e:
        raise cls.make_type_error(
          f"error in namedtuple() base constructor: {e}")

      # TODO: Make this kind of exception pattern (filter for errors then display them all at once)
      # more ergonomic.
      type_failure_msgs = []
      for field_name, field_constraint in fields_with_constraints.items():
        # TODO: figure out how to disallow users from accessing datatype fields by index!
        # TODO: gettattr() with a specific `field_name` against a `namedtuple` is apparently
        # converted into a __getitem__() call with the argument being the integer index of the field
        # with that name -- this indirection is not shown in the stack trace when overriding
        # __getitem__() to raise on `int` inputs. See https://stackoverflow.com/a/6738724 for the
        # greater context of how `namedtuple` differs from other "normal" python classes.
        field_value = getattr(this_object, field_name)
        try:
          field_constraint.validate_satisfied_by(field_value)
        except TypeConstraintError as e:
          type_failure_msgs.append(
            f"field '{field_name}' was invalid: {e}")
      if type_failure_msgs:
        raise cls.make_type_error(
          '{} type checking constructor arguments:\n{}'
          .format(pluralize(len(type_failure_msgs), 'error'),
                  '\n'.join(type_failure_msgs)))

      return this_object

    def __eq__(self, other):
      if self is other:
        return True

      # Compare types and fields.
      if type(self) != type(other):
        return False
      # Explicitly return super.__eq__'s value in case super returns NotImplemented
      return super().__eq__(other)
    # We define an attribute on the `cls` level definition of `__eq__` that will allow us to detect
    # that it has been overridden.
    __eq__._eq_override_canary = None

    def __ne__(self, other):
      return not (self == other)

    # NB: in Python 3, whenever __eq__ is overridden, __hash__() must also be
    # explicitly implemented, otherwise Python will raise "unhashable type". See
    # https://docs.python.org/3/reference/datamodel.html#object.__hash__.
    def __hash__(self):
      try:
        return super().__hash__()
      except TypeError:
        # If any fields are unhashable, we want to be able to specify which ones in the error
        # message, but we don't want to slow down the normal __hash__ code path, so we take the time
        # to break it down by field if we know the __hash__ fails for some reason.
        for field_name, value in self._asdict().items():
          try:
            hash(value)
          except TypeError as e:
            raise TypeError("For datatype object {} (type '{}'): in field '{}': {}"
                            .format(self, type(self).__name__, field_name, e))
        # If the error doesn't seem to be with hashing any of the fields, just re-raise the
        # original error.
        raise

    # NB: As datatype is not iterable, we need to override both __iter__ and all of the
    # namedtuple methods that expect self to be iterable.
    def __iter__(self):
      raise self.make_type_error("datatype object is not iterable")

    def _super_iter(self):
      return super().__iter__()

    def _asdict(self):
      """Return a new OrderedDict which maps field names to their values.

      Overrides a namedtuple() method which calls __iter__.
      """
      return OrderedDict(zip(self._fields, self._super_iter()))

    def _replace(self, **kwargs):
      """Return a new datatype object replacing specified fields with new values.

      Overrides a namedtuple() method which calls __iter__.
      """
      field_dict = self._asdict()
      field_dict.update(**kwargs)
      return type(self)(**field_dict)

    def copy(self, **kwargs):
      return self._replace(**kwargs)

    # NB: it is *not* recommended to rely on the ordering of the tuple returned by this method.
    def __getnewargs__(self):
      """Return self as a plain tuple.  Used by copy and pickle."""
      return tuple(self._super_iter())

    def __repr__(self):
      args_formatted = []
      for field_name in field_names:
        field_value = getattr(self, field_name)
        args_formatted.append(f"{field_name}={field_value!r}")
      return '{class_name}({args_joined})'.format(
        class_name=type(self).__name__,
        args_joined=', '.join(args_formatted))

    def __str__(self):
      elements_formatted = []
      for field_name in field_names:
        constraint_for_field = fields_with_constraints.get(field_name, None)
        field_value = getattr(self, field_name)
        if not constraint_for_field:
          elements_formatted.append(
            # TODO: consider using the repr of arguments in this method.
            "{field_name}={field_value}"
            .format(field_name=field_name,
                    field_value=field_value))
        else:
          elements_formatted.append(
            "{field_name}<{type_constraint}>={field_value}"
            .format(field_name=field_name,
                    type_constraint=constraint_for_field,
                    field_value=field_value))
      return '{class_name}({typed_tagged_elements})'.format(
        class_name=type(self).__name__,
        typed_tagged_elements=', '.join(elements_formatted))

  # Return a new type with the given name, inheriting from the DataType class
  # just defined, with an empty class body.
  return type(superclass_name, (DataType,), {})


class EnumVariantSelectionError(TypeCheckError):
  """Raised when an invalid variant for an enum() is constructed or matched against."""


# TODO: look into merging this with pants.util.meta.Singleton!
class ChoicesMixin(ABC):
  """A mixin which declares that the type has a fixed set of possible instances."""

  @classproperty
  @abstractmethod
  def all_variants(cls):
    """Return an iterable containing a de-duplicated list of all possible instances of this type."""


def enum(all_values):
  """A datatype which can take on a finite set of values. This method is experimental and unstable.

  Any enum subclass can be constructed with its create() classmethod. This method will use the first
  element of `all_values` as the default value, but enum classes can override this behavior by
  setting `default_value` in the class body.

  If `all_values` contains only strings, then each variant is made into an attribute on the
  generated enum class object. This allows code such as the following:

  class MyResult(enum(['success', 'not-success'])):
    pass

  MyResult.success # The same as: MyResult('success')
  MyResult.not_success # The same as: MyResult('not-success')

  Note that like with option names, hyphenated ('-') enum values are converted into attribute names
  with underscores ('_').

  :param Iterable all_values: A nonempty iterable of objects representing all possible values for
                              the enum.  This argument must be a finite, non-empty iterable with
                              unique values.
  :raises: :class:`ValueError`
  """
  # namedtuple() raises a ValueError if you try to use a field with a leading underscore.
  field_name = 'value'

  # This call to list() will eagerly evaluate any `all_values` which would otherwise be lazy, such
  # as a generator.
  all_values_realized = list(all_values)

  unique_values = OrderedSet(all_values_realized)
  if len(unique_values) == 0:
    raise ValueError("all_values must be a non-empty iterable!")
  elif len(unique_values) < len(all_values_realized):
    raise ValueError("When converting all_values ({}) to a set, at least one duplicate "
                     "was detected. The unique elements of all_values were: {}."
                     .format(all_values_realized, list(unique_values)))

  class ChoiceDatatype(datatype([field_name]), ChoicesMixin):
    # Overriden from datatype() so providing an invalid variant is catchable as a TypeCheckError,
    # but more specific.
    type_check_error_type = EnumVariantSelectionError

    @memoized_classproperty
    def _singletons(cls):
      """Generate memoized instances of this enum wrapping each of this enum's allowed values.

      NB: The implementation of enum() should use this property as the source of truth for allowed
      values and enum instances from those values.
      """
      return OrderedDict((value, cls._make_singleton(value)) for value in all_values_realized)

    @classmethod
    def _make_singleton(cls, value):
      """
      We convert uses of the constructor to call create(), so we then need to go around __new__ to
      bootstrap singleton creation from datatype()'s __new__.
      """
      return super().__new__(cls, value)

    @classproperty
    def _allowed_values(cls):
      """The values provided to the enum() type constructor, for use in error messages."""
      return list(cls._singletons.keys())

    def __new__(cls, value):
      """Create an instance of this enum.

      :param value: Use this as the enum value. If `value` is an instance of this class, return it,
                    otherwise it is checked against the enum's allowed values.
      """
      if isinstance(value, cls):
        return value

      if value not in cls._singletons:
        raise cls.make_type_error(
          "Value {!r} must be one of: {!r}."
          .format(value, cls._allowed_values))

      return cls._singletons[value]

    # TODO: figure out if this will always trigger on primitives like strings, and what situations
    # won't call this __eq__ (and therefore won't raise like we want). Also look into whether there
    # is a way to return something more conventional like `NotImplemented` here that maintains the
    # extra caution we're looking for.
    def __eq__(self, other):
      """Redefine equality to avoid accidentally comparing against a non-enum."""
      if other is None:
        return False
      if type(self) != type(other):
        raise self.make_type_error(
          "when comparing {!r} against {!r} with type '{}': "
          "enum equality is only defined for instances of the same enum class!"
          .format(self, other, type(other).__name__))
      return super().__eq__(other)
    # Redefine the canary so datatype __new__ doesn't raise.
    __eq__._eq_override_canary = None

    # NB: as noted in datatype(), __hash__ must be explicitly implemented whenever __eq__ is
    # overridden. See https://docs.python.org/3/reference/datamodel.html#object.__hash__.
    def __hash__(self):
      return super().__hash__()

    def resolve_for_enum_variant(self, mapping):
      """Return the object in `mapping` with the key corresponding to the enum value.

      `mapping` is a dict mapping enum variant value -> arbitrary object. All variant values must be
      provided.

      NB: The objects in `mapping` should be made into lambdas if lazy execution is desired, as this
      will "evaluate" all of the values in `mapping`.
      """
      keys = frozenset(mapping.keys())
      if keys != frozenset(self._allowed_values):
        raise self.make_type_error(
          "pattern matching must have exactly the keys {} (was: {})"
          .format(self._allowed_values, list(keys)))
      match_for_variant = mapping[self.value]
      return match_for_variant

    @classproperty
    def all_variants(cls):
      """Iterate over all instances of this enum, in the declared order.

      NB: resolve_for_enum_variant() should be used instead of this method for performing
      conditional logic based on an enum instance's value.
      """
      return cls._singletons.values()

  # Python requires creating an explicit closure to save the value on each loop iteration.
  accessor_generator = lambda case: lambda cls: cls(case)
  for case in all_values_realized:
    if SubclassesOf(str).satisfied_by(case):
      accessor = classproperty(accessor_generator(case))
      attr_name = re.sub(r'-', '_', case)
      setattr(ChoiceDatatype, attr_name, accessor)

  return ChoiceDatatype


# TODO: make this error into an attribute on the `TypeConstraint` class object!
class TypeConstraintError(TypeError):
  """Indicates a :class:`TypeConstraint` violation."""


class TypeConstraint(ABC):
  """Represents a type constraint.

  Not intended for direct use; instead, use one of :class:`SuperclassesOf`, :class:`Exactly` or
  :class:`SubclassesOf`.
  """

  def __init__(self, description):
    """Creates a type constraint centered around the given types.

    The type constraint is satisfied as a whole if satisfied for at least one of the given types.

    :param str description: A concise, readable description of what the type constraint represents.
                            Used directly as the __str__ implementation.
    """
    self._description = description

  @abstractmethod
  def satisfied_by(self, obj):
    """Return `True` if the given object satisfies this type constraint.

    :rtype: bool
    """

  def make_type_constraint_error(self, obj, constraint):
    return TypeConstraintError(
      "value {!r} (with type {!r}) must satisfy this type constraint: {}."
      .format(obj, type(obj).__name__, constraint))

  # TODO: disallow overriding this method with some form of mixin/decorator along with datatype
  # __eq__!
  def validate_satisfied_by(self, obj):
    """Return `obj` if the object satisfies this type constraint, or raise.

    :raises: `TypeConstraintError` if `obj` does not satisfy the constraint.
    """

    if self.satisfied_by(obj):
      return obj

    raise self.make_type_constraint_error(obj, self)

  def __ne__(self, other):
    return not (self == other)

  def __str__(self):
    return self._description


class TypeOnlyConstraint(TypeConstraint):
  """A `TypeConstraint` predicated only on the object's type.

  `TypeConstraint` subclasses may override `.satisfied_by()` to perform arbitrary validation on the
  object itself -- however, this class implements `.satisfied_by()` with a guarantee that it will
  only act on the object's `type` via `.satisfied_by_type()`. This kind of type checking is faster
  and easier to understand than the more complex validation allowed by `.satisfied_by()`.
  """

  def __init__(self, *types):
    """Creates a type constraint based on some logic to match the given types.

    NB: A `TypeOnlyConstraint` implementation should ensure that the type constraint is satisfied as
    a whole if satisfied for at least one of the given `types`.

    :param type *types: The types this constraint will match in some way.
    """

    if not types:
      raise ValueError('Must supply at least one type')
    if any(not isinstance(t, type) for t in types):
      raise TypeError(f'Supplied types must be types. {types!r}')

    if len(types) == 1:
      type_list = types[0].__name__
    else:
      type_list = ' or '.join(t.__name__ for t in types)
    description = '{}({})'.format(type(self).__name__, type_list)

    super().__init__(description=description)

    # NB: This is made into a tuple so that we can use self._types in issubclass() and others!
    self._types = tuple(types)

  # TODO(#7114): remove this after the engine is converted to use `TypeId` instead of
  # `TypeConstraint`!
  @property
  def types(self):
    return self._types

  @abstractmethod
  def satisfied_by_type(self, obj_type):
    """Return `True` if the given object satisfies this type constraint.

    :rtype: bool
    """

  def satisfied_by(self, obj):
    return self.satisfied_by_type(type(obj))

  def __hash__(self):
    return hash((type(self), self._types))

  def __eq__(self, other):
    return type(self) == type(other) and self._types == other._types

  def __repr__(self):
    constrained_type = ', '.join(t.__name__ for t in self._types)
    return ('{type_constraint_type}({constrained_type})'
      .format(type_constraint_type=type(self).__name__,
              constrained_type=constrained_type))


class SuperclassesOf(TypeOnlyConstraint):
  """Objects of the exact type as well as any super-types are allowed."""

  def satisfied_by_type(self, obj_type):
    return any(issubclass(t, obj_type) for t in self._types)


class Exactly(TypeOnlyConstraint):
  """Only objects of the exact type are allowed."""

  def satisfied_by_type(self, obj_type):
    return obj_type in self._types

  def graph_str(self):
    if len(self.types) == 1:
      return self.types[0].__name__
    else:
      return repr(self)


class SubclassesOf(TypeOnlyConstraint):
  """Objects of the exact type as well as any sub-types are allowed."""

  def satisfied_by_type(self, obj_type):
    return issubclass(obj_type, self._types)


class TypedCollection(TypeConstraint):
  """A `TypeConstraint` which accepts a TypeOnlyConstraint and validates a collection."""

  @memoized_classproperty
  def iterable_constraint(cls):
    """Define what kind of collection inputs are accepted by this type constraint.

    :rtype: TypeConstraint
    """
    return SubclassesOf(Iterable)

  # TODO: extend TypeConstraint to specify includes and excludes in a single constraint!
  @classproperty
  def exclude_iterable_constraint(cls):
    """Define what collection inputs are *not* accepted by this type constraint.

    Strings (unicode and byte) in Python are considered iterables of substrings, but we only want
    to allow explicit collection types.

    :rtype: TypeConstraint
    """
    return SubclassesOf(str, bytes)

  def __init__(self, constraint):
    """Create a `TypeConstraint` which validates each member of a collection with `constraint`.

    :param TypeOnlyConstraint constraint: the `TypeConstraint` to apply to each element. This is
                                          currently required to be a `TypeOnlyConstraint` to avoid
                                          complex prototypal type relationships.
    """

    if not isinstance(constraint, TypeOnlyConstraint):
      raise TypeError("constraint for collection must be a {}! was: {}"
                      .format(TypeOnlyConstraint.__name__, constraint))

    description = '{}({})'.format(type(self).__name__, constraint)

    self._constraint = constraint

    super().__init__(description=description)

  def _is_iterable(self, obj):
    return (self.iterable_constraint.satisfied_by(obj)
            and not self.exclude_iterable_constraint.satisfied_by(obj))

  # TODO: consider making this a private method of TypeConstraint, as it now duplicates the logic in
  # self.validate_satisfied_by()!
  def satisfied_by(self, obj):
    return (self._is_iterable(obj)
            and all(self._constraint.satisfied_by(el) for el in obj))

  def make_collection_type_constraint_error(self, base_obj, el):
    base_error = self.make_type_constraint_error(el, self._constraint)
    return TypeConstraintError("in wrapped constraint {} matching iterable object {}: {}"
                               .format(self, base_obj, base_error))

  def validate_satisfied_by(self, obj):
    if not self._is_iterable(obj):
      base_iterable_error = self.make_type_constraint_error(obj, self.iterable_constraint)
      raise TypeConstraintError(
        "in wrapped constraint {}: {}\nNote that objects matching {} are not considered iterable."
        .format(self, base_iterable_error, self.exclude_iterable_constraint))
    for el in obj:
      if not self._constraint.satisfied_by(el):
        raise self.make_collection_type_constraint_error(obj, el)
    return obj

  def __hash__(self):
    return hash((type(self), self._constraint))

  def __eq__(self, other):
    return type(self) == type(other) and self._constraint == other._constraint

  def __repr__(self):
    return ('{type_constraint_type}({constraint!r})'
            .format(type_constraint_type=type(self).__name__,
                    constraint=self._constraint))


# TODO(#6742): Useful type constraints for datatype fields before we start using mypy type hints!
hashable_collection_constraint = Exactly(tuple)


class HashableTypedCollection(TypedCollection):
  iterable_constraint = hashable_collection_constraint


string_type = Exactly(str)
string_list = TypedCollection(string_type)
string_optional = Exactly(str, type(None))


hashable_string_list = HashableTypedCollection(string_type)
