# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
import re
import sys
from collections import OrderedDict, namedtuple

from abc import abstractmethod
from twitter.common.collections import OrderedSet

from pants.util.memo import memoized
from pants.util.meta import AbstractClass


def datatype(*args, **kwargs):
  """A wrapper for `namedtuple` that accounts for the type of the object in equality."""
  class DataType(namedtuple(*args, **kwargs)):
    __slots__ = ()

    def __eq__(self, other):
      if self is other:
        return True

      # Compare types and fields.
      if type(self) != type(other):
        return False
      # Explicitly return super.__eq__'s value in case super returns NotImplemented
      return super(DataType, self).__eq__(other)

    def __ne__(self, other):
      return not (self == other)

    # NB: As datatype is not iterable, we need to override both __iter__ and all of the
    # namedtuple methods that expect self to be iterable.
    def __iter__(self):
      raise TypeError("'{}' object is not iterable".format(type(self).__name__))

    def _asdict(self):
      '''Return a new OrderedDict which maps field names to their values'''
      return OrderedDict(zip(self._fields, super(DataType, self).__iter__()))

    def _replace(_self, **kwds):
      '''Return a new datatype object replacing specified fields with new values'''
      result = _self._make(map(kwds.pop, _self._fields, super(DataType, _self).__iter__()))
      if kwds:
        raise ValueError('Got unexpected field names: %r' % kwds.keys())
      return result

    def __getnewargs__(self):
      '''Return self as a plain tuple.  Used by copy and pickle.'''
      return tuple(super(DataType, self).__iter__())

  return DataType


class TypedDatatypeClassConstructionError(Exception):

  # TODO(cosmicexplorer): make some wrapper exception class to make this kind of
  # prefixing easy (maybe using a class field format string?).
  def __init__(self, type_name, msg, *args, **kwargs):
    full_msg =  "error: while trying to generate typed datatype {}: {}".format(
      type_name, msg)
    super(TypedDatatypeClassConstructionError, self).__init__(
      full_msg, *args, **kwargs)


class TypedDatatypeInstanceConstructionError(Exception):

  def __init__(self, type_name, msg, *args, **kwargs):
    full_msg = "error: in constructor of type {}: {}".format(type_name, msg)
    super(TypedDatatypeInstanceConstructionError, self).__init__(
      full_msg, *args, **kwargs)


class TypeCheckError(TypedDatatypeInstanceConstructionError):

  def __init__(self, type_name, msg, *args, **kwargs):
    formatted_msg = "type check error:\n{}".format(msg)
    super(TypeCheckError, self).__init__(
      type_name, formatted_msg, *args, **kwargs)


class TypeConstraintError(TypeError):
  """Indicates a :class:`TypeConstraint` violation."""


class TypeConstraint(AbstractClass):
  """Represents a type constraint.

  Not intended for direct use; instead, use one of :class:`SuperclassesOf`, :class:`Exact` or
  :class:`SubclassesOf`.
  """

  def __init__(self, *types, **kwargs):
    """Creates a type constraint centered around the given types.

    The type constraint is satisfied as a whole if satisfied for at least one of the given types.

    :param type *types: The focus of this type constraint.
    :param str description: A description for this constraint if the list of types is too long.
    """
    # TODO(cosmicexplorer): Could we turn `types` into a frozenset? I'm not sure
    # there would ever be enough types to warrant this for performance
    # reasons. self.types claims that it returns a tuple, but we're not checking
    # that here, just that it's iterable, so some more validation or conversion
    # needs to be done somewhere.
    if not types:
      raise ValueError('Must supply at least one type')
    if any(not isinstance(t, type) for t in types):
      raise TypeError('Supplied types must be types. {!r}'.format(types))

    self._types = types
    self._desc = kwargs.get('description', None)

  @property
  def types(self):
    """Return the subject types of this type constraint.

    :type: tuple of type
    """
    return self._types

  def satisfied_by(self, obj):
    """Return `True` if the given object satisfies this type constraint.

    :rtype: bool
    """
    return self.satisfied_by_type(type(obj))

  @abstractmethod
  def satisfied_by_type(self, obj_type):
    """Return `True` if the given object satisfies this type constraint.

    :rtype: bool
    """

  def __hash__(self):
    return hash((type(self), self._types))

  def __eq__(self, other):
    return type(self) == type(other) and self._types == other._types

  def __ne__(self, other):
    return not (self == other)

  def __str__(self):
    if self._desc:
      constrained_type = '({})'.format(self._desc)
    else:
      if len(self._types) == 1:
        constrained_type = self._types[0].__name__
      else:
        constrained_type = '({})'.format(', '.join(t.__name__ for t in self._types))
    return '{variance_symbol}{constrained_type}'.format(variance_symbol=self._variance_symbol,
                                                        constrained_type=constrained_type)

  def __repr__(self):
    if self._desc:
      constrained_type = self._desc
    else:
      constrained_type = ', '.join(t.__name__ for t in self._types)
    return ('{type_constraint_type}({constrained_type})'
      .format(type_constraint_type=type(self).__name__,
                    constrained_type=constrained_type))


class SuperclassesOf(TypeConstraint):
  """Objects of the exact type as well as any super-types are allowed."""

  _variance_symbol = '-'

  def satisfied_by_type(self, obj_type):
    return any(issubclass(t, obj_type) for t in self._types)


class Exactly(TypeConstraint):
  """Only objects of the exact type are allowed."""

  _variance_symbol = '='

  def satisfied_by_type(self, obj_type):
    return obj_type in self._types

  def graph_str(self):
    if len(self.types) == 1:
      return self.types[0].__name__
    else:
      return repr(self)


class SubclassesOf(TypeConstraint):
  """Objects of the exact type as well as any sub-types are allowed."""

  _variance_symbol = '+'

  def satisfied_by_type(self, obj_type):
    return issubclass(obj_type, self._types)


class FieldType(Exactly):
  """???"""

  class FieldTypeConstructionError(Exception):
    """Raised on invalid arguments on creation."""

  class FieldTypeNameError(FieldTypeConstructionError):
    """Raised if a type object has an invalid name."""

  CAMEL_CASE_TYPE_NAME = re.compile('\A([A-Z][a-z]*)+\Z')
  CAMEL_CASE_SPLIT_PATTERN = re.compile('[A-Z][a-z]*')

  LOWER_CASE_TYPE_NAME = re.compile('\A[a-z]+\Z')

  @classmethod
  def _transform_type_field_name(cls, type_name):
    if cls.LOWER_CASE_TYPE_NAME.match(type_name):
      # double underscore here ensures no clash with camel-case type names
      return 'primitive__{}'.format(type_name)

    if cls.CAMEL_CASE_TYPE_NAME.match(type_name):
      split_by_camel_downcased = []
      for m in cls.CAMEL_CASE_SPLIT_PATTERN.finditer(type_name):
        camel_group = m.group(0)
        downcased = camel_group.lower()
        split_by_camel_downcased.append(downcased)
      return '_'.join(split_by_camel_downcased)

    raise cls.FieldTypeNameError(
      "Type name '{}' must be camel-cased with an initial capital, "
      "or all lowercase. Only ASCII alphabetical characters are allowed."
      .format(type_name))

  def __init__(self, single_type, field_name):
    if not isinstance(single_type, type):
      raise self.FieldTypeConstructionError(
        "single_type is not a type: was {} ({})."
        .format(single_type, type(single_type)))
    if not isinstance(field_name, str):
      raise self.FieldTypeConstructionError(
        "field_name is not a str: was {} ({})"
        .format(field_name, type(field_name)))

    super(FieldType, self).__init__(single_type)

    self._field_name = field_name

  @property
  def field_name(self):
    return self._field_name

  @property
  def field_type(self):
    return self.types[0]

  def validate_satisfies_field(self, obj):
    """Return `obj` if it satisfies this type constraint, or raise.

    :raises: `TypeConstraintError` if the given object does not satisfy this
    type constraint.
    """
    if self.satisfied_by(obj):
      return obj

    raise TypeConstraintError(
      "value {!r} (with type {!r}) must be an instance of type {!r}."
      .format(obj, type(obj).__name__, self.field_type.__name__))

  def __repr__(self):
    fmt_str = 'FieldType({field_type}, {field_name!r})'
    return fmt_str.format(field_type=self.field_type.__name__,
                          field_name=self.field_name)

  @classmethod
  def create_from_type(cls, type_obj):
    """???"""
    if not isinstance(type_obj, type):
      raise cls.FieldTypeConstructionError(
        "type_obj is not a type: was {!r} ({!r})"
        .format(type_obj, type(type_obj)))
    transformed_type_name = cls._transform_type_field_name(type_obj.__name__)
    return cls(type_obj, str(transformed_type_name))


# TODO (but maybe not): make a `newtype` method as well, which wraps an existing
# type and gives it a new name, and generates an `@rule` to convert <new type>
# -> <existing type> by accessing the (only) field (of type <existing type>).
def typed_datatype(type_name, field_decls):
  """A wrapper over namedtuple which accepts a dict of field names and types.

  This can be used to very concisely define classes which have fields that are
  type-checked at construction.
  """

  type_name = str(type_name)

  if not isinstance(field_decls, tuple):
    raise TypedDatatypeClassConstructionError(
      type_name,
      "field_decls is not a tuple: {!r}".format(field_decls))
  if field_decls is ():
    raise TypedDatatypeClassConstructionError(
      type_name,
      "no fields were declared")

  # TODO: Make this kind of exception pattern (filter for errors then display
  # them all at once) more ergonomic.
  type_constraints = OrderedSet()
  invalid_decl_errs = []
  for maybe_decl in field_decls:
    try:
      field_constraint = FieldType.create_from_type(maybe_decl)
    except FieldType.FieldTypeConstructionError as e:
      invalid_decl_errs.append(str(e))
      continue

    if field_constraint in type_constraints:
      invalid_decl_errs.append(
        "type constraint '{}' was already used as a field"
        .format(field_constraint))
    else:
      type_constraints.add(field_constraint)
  if invalid_decl_errs:
    raise TypedDatatypeClassConstructionError(
      type_name,
      "invalid field declarations:\n{}".format('\n'.join(invalid_decl_errs)))

  # This is a tuple of FieldType instances for the arguments given.
  field_type_tuple = tuple(type_constraints)
  # This is a tuple of type names, for use in error messages.
  type_names_joined = "({})".format(
    ' '.join("{},".format(f.field_type.__name__) for f in field_type_tuple))

  datatype_cls = datatype(type_name, [t.field_name for t in field_type_tuple])

  # TODO(cosmicexplorer): override the __repr__()!
  class TypedDatatype(datatype_cls):

    def __new__(cls, *args, **kwargs):
      if kwargs:
        raise TypedDatatypeInstanceConstructionError(
          type_name,
          "typed_datatype() subclasses can only be constructed with positional "
          "arguments! The class {class_name} requires {field_types} "
          "as arguments.\n"
          "The args provided were: {args!r}.\n"
          "The kwargs provided were: {kwargs!r}.\n"
          .format(class_name=cls.__name__,
                  field_types=type_names_joined,
                  args=args,
                  kwargs=kwargs))

      if len(args) != len(field_type_tuple):
        raise TypedDatatypeInstanceConstructionError(
          type_name,
          "{num_args} args were provided, "
          "but expected {expected_num_args}: {field_types}. "
          "The args provided were: {args!r}."
          .format(num_args=len(args),
                  expected_num_args=len(field_type_tuple),
                  field_types=type_names_joined,
                  args=args))

      type_failure_msgs = []
      for field_idx, field_value in enumerate(args):
        constraint_for_field = field_type_tuple[field_idx]
        try:
          constraint_for_field.validate_satisfies_field(field_value)
        except TypeConstraintError as e:
          type_failure_msgs.append(
            "field '{}' was invalid: {}"
            .format(constraint_for_field.field_name, e))
      if type_failure_msgs:
        raise TypeCheckError(type_name, '\n'.join(type_failure_msgs))

      return super(TypedDatatype, cls).__new__(cls, *args)

    def __repr__(self):
      formatted_args = [repr(arg) for arg in self.__getnewargs__()]
      return '{class_name}({args_joined})'.format(
        class_name=type(self).__name__,
        args_joined=', '.join(formatted_args))

    def __str__(self):
      arg_tuple = self.__getnewargs__()
      elements_formatted = []
      for field_idx, field_value in enumerate(arg_tuple):
        constraint_for_field = field_type_tuple[field_idx]
        elements_formatted.append("{field_name}<{type_name}>={arg}".format(
          field_name=constraint_for_field.field_name,
          type_name=constraint_for_field.field_type.__name__,
          arg=field_value))
      return '{class_name}({typed_tagged_elements})'.format(
        class_name=type(self).__name__,
        typed_tagged_elements=', '.join(elements_formatted))

    @classmethod
    def make_type_error(cls, msg):
      return TypeCheckError(cls.__name__, msg)

  return TypedDatatype


# @typed_data(int, str)
# class MyTypedData(SomeMixin):
#   # source code...
#
#         |
#         |
#         V
#
# class MyTypedData(typed_datatype('MyTypedData', (int, str)), SomeMixin):
#   # source code...
def typed_data(*fields):

  def from_class(cls):
    if not inspect.isclass(cls):
      raise ValueError("The @typed_data() decorator must be applied "
                       "innermost of all decorators.")

    typed_base = typed_datatype(cls.__name__, tuple(fields))
    all_bases = (typed_base,) + cls.__bases__

    return type(cls.__name__, all_bases, cls.__dict__)

  return from_class


class Collection(object):
  """Constructs classes representing collections of objects of a particular type."""

  @classmethod
  @memoized
  def of(cls, *element_types):
    union = '|'.join(element_type.__name__ for element_type in element_types)
    type_name = b'{}.of({})'.format(cls.__name__, union)
    supertypes = (cls, datatype('Collection', ['dependencies']))
    properties = {'element_types': element_types}
    collection_of_type = type(type_name, supertypes, properties)

    # Expose the custom class type at the module level to be pickle compatible.
    setattr(sys.modules[cls.__module__], type_name, collection_of_type)

    return collection_of_type
