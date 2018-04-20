# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
from collections import OrderedDict, namedtuple

from pants.util.memo import memoized


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


class TypeMatcher(datatype('TypeMatcher', ['types'])):

  class ConstructionError(Exception):
    pass

  def __new__(cls, types):
    try:
      type_set = frozenset(types)
    except TypeError as e:
      raise cls.ConstructionError(
        "'types' argument must be convertible to frozenset: '{}'".format(types))

    if not type_set:
      raise cls.ConstructionError("at least one type must be provided to Union")

    non_type_args = []
    for ty in type_set:
      if not isinstance(ty, type):
        non_type_args.append(ty)
    if non_type_args:
      raise cls.ConstructionError(
        "all elements of 'types' must be a type. non-type args: '{}'"
        .format(non_type_args))

    return super(TypeMatcher, cls).__new__(cls, types=type_set)

  @classmethod
  def create(cls, decl_val):
    if isinstance(decl_val, cls):
      return decl_val

    if isinstance(decl_val, type):
      return cls(types=[decl_val])

    # Interpret it as an iterable of types, or raise ConstructionError.
    return cls(types=decl_val)

  def matches_value(self, val):
    """Return whether or not the argument matches the type described by this
  class."""
    return type(val) in self.types

  def compose(self, rhs):
    """Return a TypeMatcher which matches either this or another TypeMatcher."""
    all_types = self.types | rhs.types
    return TypeMatcher(types=all_types)


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

  # Turn every type declaration into an instance of TypeMatcher, and place the
  # results in processed_type_decls.
  # TODO: Make this kind of exception pattern (filter for errors then display
  # them all at once) more ergonomic.
  processed_type_decls = {}
  invalid_type_decls = []
  for name, maybe_decl in field_decls.items():
    try:
      processed_type_decls[name] = TypeMatcher.create(maybe_decl)
    except TypeMatcher.ConstructionError as e:
      invalid_type_decls.append(
        "in field '{}': {}".format(name, e))

  if invalid_type_decls:
    raise TypedDatatypeClassConstructionError(
      type_name,
      "invalid field declarations:\n{}".format('\n'.join(invalid_type_decls)))

  field_name_set = frozenset(processed_type_decls.keys())

  datatype_cls = datatype(type_name, list(field_name_set))

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
        if not field_type.matches_value(field_value):
          type_failure_msgs.append(
            "field '{}' is not an instance of '{}'. type='{}', value='{}'"
            .format(field_name, field_type, type(field_value), field_value))
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
