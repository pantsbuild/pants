# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
from collections import OrderedDict, namedtuple

from abc import abstractmethod

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
    full_msg =  "while trying to generate typed dataype '{}': {}".format(
      type_name, msg)
    super(TypedDatatypeClassConstructionError, self).__init__(
      full_msg, *args, **kwargs)


class TypedDatatypeInstanceConstructionError(Exception):

  def __init__(self, type_name, msg, *args, **kwargs):
    full_msg = "in constructor of type '{}': {}".format(type_name, msg)
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

  def validate_satisfied_by(self, obj):
    """Return `obj` if it satisfies this type constraint, or raise.

    :raises: `TypeConstraintError` if the given object does not satisfy this
    type constraint.
    """

    if self.satisfied_by(obj):
      return obj

    raise TypeConstraintError(
      "Value '{}' (with type '{}') did not satisfy type constraint '{!r}'."
      .format(obj, type(obj).__name__, self))

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

  @classmethod
  def from_type_or_collection(cls, maybe_decl):
    if isinstance(maybe_decl, cls):
      return maybe_decl
    if isinstance(maybe_decl, type):
      return cls(maybe_decl)

    try:
      return cls(*maybe_decl)
    except TypeError:
      raise TypeConstraintError(
        "value '{}' could not be interpreted as an Exactly type constraint, "
        "a specific type, or a collection of types".format(maybe_decl))

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


def typed_datatype(type_name, field_decls):
  """A wrapper over namedtuple which accepts a dict of field names and types.

  This can be used to very concisely define classes which have fields that are
  type-checked at construction.
  """

  type_name = str(type_name)

  if not isinstance(field_decls, dict):
    raise TypedDatatypeClassConstructionError(
      type_name,
      "field_decls is not a dict: '{}'".format(field_decls))
  if not field_decls:
    raise TypedDatatypeClassConstructionError(
      type_name,
      "no fields were declared")

  # Turn every type declaration into an instance of Exactly, and place the
  # results in processed_type_decls.
  # TODO: Make this kind of exception pattern (filter for errors then display
  # them all at once) more ergonomic.
  processed_type_decls = {}
  invalid_type_decls = []
  for name, maybe_decl in field_decls.items():
    try:
      processed_type_decls[name] = Exactly.from_type_or_collection(maybe_decl)
    except TypeConstraintError as e:
      invalid_type_decls.append(
        "in field '{}': {}"
        .format(name, e))
  if invalid_type_decls:
    raise TypedDatatypeClassConstructionError(
      type_name,
      "invalid field declarations:\n{}".format('\n'.join(invalid_type_decls)))

  field_name_set = frozenset(processed_type_decls.keys())

  datatype_cls = datatype(type_name, list(field_name_set))

  # TODO(cosmicexplorer): Make the repr use the 'description' kwarg in
  # TypeConstraint?
  class TypedDatatype(datatype_cls):

    # We intentionally disallow positional arguments here.
    def __new__(cls, *args, **kwargs):
      if args:
        raise TypedDatatypeInstanceConstructionError(
          type_name,
          "no positional args are allowed in this constructor. "
          "the args were: '{}'".format(args))

      given_field_set = frozenset(kwargs.keys())

      not_provided = given_field_set - field_name_set
      if not_provided:
        raise TypedDatatypeInstanceConstructionError(
          type_name,
          "must provide fields '{}'".format(not_provided))

      unrecognized = field_name_set - given_field_set
      if unrecognized:
        raise TypedDatatypeInstanceConstructionError(
          type_name,
          "unrecognized fields were provided: '{}'".format(unrecognized))

      type_failure_msgs = []
      for field_name, field_value in kwargs.items():
        field_type = processed_type_decls[field_name]
        try:
          field_type.validate_satisfied_by(field_value)
        except TypeConstraintError as e:
          type_failure_msgs.append(
            "field '{}' was invalid: {}"
            .format(field_name, field_value, e))
      if type_failure_msgs:
        raise TypeCheckError(type_name, '\n'.join(type_failure_msgs))

      return super(TypedDatatype, cls).__new__(cls, **kwargs)

  return TypedDatatype


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
