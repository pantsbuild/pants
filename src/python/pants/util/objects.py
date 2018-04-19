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


class TypeDecl(AbstractClass):

  class ConstructionError(Exception):
    pass

  @abstractmethod
  def matches_value(self, val):
    """Return whether or not the argument matches the type described by this
  class.
    """

  @abstractmethod
  def as_union(self):
    """Return a version of this object which is an instance of Union."""

  def compose(self, rhs):
    """Return a TypeDecl which matches either this or another TypeDecl."""
    self_types = self.as_union().types
    rhs_types = rhs.as_union().types
    all_types = self_types + rhs_types
    return Union(*all_types)


class SimpleTypeDecl(datatype('SimpleTypeDecl', ['matching_type']), TypeDecl):

  def __new__(cls, matching_type):
    if not isinstance(matching_type, type):
      raise cls.ConstructionError(
        "argument should be a type: '{}'".format(matching_type))

    return super(SimpleTypeDecl, cls).__new__(cls, matching_type)

  def matches_value(self, val):
    return isinstance(val, self.matching_type)

  def as_union(self):
    return Union(self.matching_type)


class Union(datatype('Union', ['types']), TypeDecl):

  def __new__(cls, *types):
    if len(types) == 0:
      raise cls.ConstructionError("at least one type must be provided to Union")
    if not all([isinstance(ty, type) for ty in types]):
      raise cls.ConstructionError(
        "all arguments to Union should be types: '{}'".format(types))

    return super(Union, cls).__new__(cls, types)

  def matches_value(self, val):
    return any([isinstance(val, ty) for ty in self.types])

  def as_union(self):
    return self


StrOrUnicode = Union(str, unicode)


def typed_datatype(type_name, field_decls):
  if not (isinstance(type_name, str) or isinstance(type_name, unicode)):
    raise TypedDatatypeClassConstructionError(
      repr(type_name),
      "type_name '{}' is not a str or unicode".format(repr(type_name)))

  if not isinstance(field_decls, dict):
    raise TypedDatatypeClassConstructionError(
      type_name,
      "field_decls is not a dict: '{}'".format(field_decls))

  if not field_decls:
    raise TypedDatatypeClassConstructionError(
      type_name,
      "no fields were declared")

  # TODO: Make this kind of exception pattern (filter for errors then display
  # them all at once) more ergonomic.
  processed_type_decls = {}
  invalid_type_decls = []
  for name, cls in field_decls.items():
    if isinstance(cls, SimpleTypeDecl) or isinstance(cls, Union):
      processed_type_decls[name] = cls
      continue
    if isinstance(cls, type):
      try:
        processed_type_decls[name] = SimpleTypeDecl(cls)
      except TypeDecl.ConstructionError as e:
        invalid_type_decls.append("in field '{}': {}".format(name, e))
      continue
    if isinstance(cls, list):
      try:
        processed_type_decls[name] = Union(*cls)
      except TypeDecl.ConstructionError as e:
        invalid_type_decls.append("in field '{}': {}".format(name, e))
      continue
    else:
      invalid_type_decls.append(
        "field '{}' was not declared as a type or union of types: '{}'"
        .format(name, cls))
  if invalid_type_decls:
    raise TypedDatatypeClassConstructionError(
      type_name,
      "field types were not a type object or list of type objects:\n{}"
      .format('\n'.join(invalid_type_decls)))

  field_name_set = frozenset(field_decls.keys())

  datatype_cls = datatype(type_name, list(field_name_set))

  class TypedDatatype(datatype_cls):

    # We intentionally disallow positional arguments here.
    def __new__(cls, **kwargs):
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
        field_type = field_decls[field_name]
        if isinstance(field_type, type):
          if not isinstance(field_value, field_type):
            type_failure_msgs.append(
              "field '{}' is not an instance of '{}'. type='{}', value='{}'"
              .format(field_name, field_type, type(field_value), field_value))
        elif isinstance(field_type, list):
          # NB: We assume here that if the type is a list, each element is a
          # type object, because we checked that in the class constructor.
          # TODO: check the other if branch?
          if not any([isinstance(field_value, ty) for ty in field_type]):
            type_failure_msgs.append(
              "field '{}' is not an instance of any of '{}'. "
              "type='{}', value='{}'"
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
