# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

import six

from pants.util.meta import AbstractClass


class TypeConstraint(AbstractClass):
  """Represents a type constraint.

  Not intended for direct use, instead use one of :class:`SuperclassesOf`, :class:`Exact` or
  :class:`SubclassesOf`.
  """

  def __init__(self, type_):
    """Creates a type constraint centered around the given type.

    :param type type_: The focus of this type constraint.
    """
    self._type = type_

  @abstractmethod
  def satisfied_by(self, obj):
    """Return `True` if the given object satisfies this type constraint.

    :rtype: bool
    """

  def __hash__(self):
    return hash((type(self), self._type))

  def __eq__(self, other):
    return type(self) == type(other) and self._type == other._type

  def __str__(self):
    return '{variance_symbol}{constrained_type}'.format(variance_symbol=self._variance_symbol,
                                                        constrained_type=self._type.__name__)

  def __repr__(self):
    return ('{type_constraint_type}({constrained_type})'
            .format(type_constraint_type=type(self).__name__, constrained_type=self._type.__name__))


class SuperclassesOf(TypeConstraint):
  """Objects of the exact type as well as any super types are allowed."""

  _variance_symbol = '-'

  def satisfied_by(self, obj):
    return issubclass(self._type, type(obj))


class Exactly(TypeConstraint):
  """Only objects of the exact type are allowed."""

  _variance_symbol = '='

  def satisfied_by(self, obj):
    return self._type == type(obj)


class SubclassesOf(TypeConstraint):
  """Objects of the exact type as well as any sub types are allowed."""

  _variance_symbol = '+'

  def satisfied_by(self, obj):
    return issubclass(type(obj), self._type)


class AddressError(Exception):
  """Indicates an error assigning or resolving an address."""


class Addressed(object):
  """Describes an addressed item that meets a given type constraint."""

  def __init__(self, type_constraint, address_spec):
    self._type_constraint = type_constraint
    self._address_spec = address_spec

  @property
  def type_constraint(self):
    """The type constraint the addressed item must satisfy.

    :rtype: :class:`TypeConstraint`
    """
    return self._type_constraint

  @property
  def address_spec(self):
    """The address of the object that, when resolved, should meet the type constraint specified.

    :returns: The serialized form of the address; aka. an address 'spec'.
    :rtype: string
    """
    return self._address_spec

  def __repr__(self):
    return 'Addressed(type_constraint={!r}, address={!r})'.format(self._type_constraint,
                                                                  self._address_spec)


def addressable(type_constraint, value):
  """Marks a value as conforming to a given type constraint.

  The value may be a 'pointer', aka. an :class:`Addressed` instance that is lazily resolved via
  address and checked against the type constraint at resolve time.

  :param type_constraint: The type constraint the value must satisfy.
  :type type_constraint: :class:`TypeConstraint`
  :param value: An object satisfying the type constraint or else a string encoding the address such
                an object should be resolved from; aka. a 'pointer'.
  :returns: The `value` if it satisfies the type constraint directly or else an :class:`Addressed`
            pointer to a value to resolve later.
  """
  if value is None:
    return None
  elif type_constraint.satisfied_by(value):
    return value
  # TODO(John Sirois): This case is only here to support the `parse_python_assignments` parsing
  # scheme which is the only parsing scheme that doubly constructs it objects (the second
  # construction that injects a `name` parameter discovered in the 1st construction triggers this
  # case).  Consider removing this case if the `parse_python_assignments` parsing scheme is dropped.
  elif isinstance(value, Addressed) and type_constraint == value.type_constraint:
    return value
  elif isinstance(value, six.string_types):
    return Addressed(type_constraint, value)
  else:
    raise AddressError('The given value is not an address or an {!r}: {!r}'
                       .format(type_constraint, value))


def addressables(type_constraint, values):
  """Marks a list's values as satisfying a given type constraint.

  Some (or all) elements of the list may be :class:`Addressed` elements to resolve later.

  :param type_constraint: The type constraint the list's values must all satisfy.
  :type type_constraint: :class:`TypeConstraint`
  :param values: An iterable of objects satisfying the type constraint or else strings encoding the
                 address such objects should be resolved from; aka. 'pointers'.
  :type values: :class:`collections.Iterable`
  :returns: A list whose elements are values satisfying the type constraint directly or else are
            :class:`Addressed` pointers to values to resolve later.
  :rtype: list
  """
  # TODO(John Sirois): Instead of re-traversing all lists later to hydrate any potentially contained
  # Addressed objects, this could return a (marker) type.  The hydration could then avoid deep
  # introspection and just look for a - say - `Resolvable` value, and only resolve those.  Only if
  # perf is being tweaked might this need to be addressed.
  return [addressable(type_constraint, v) for v in values] if values else []


def addressable_mapping(type_constraint, mapping):
  """Marks a dicts's values as satisfying a given type constraint.

  Some (or all) values in the dict may be :class:`Addressed` values to resolve later.

  :param type_constraint: The type constraint the dict's values must all satisfy.
  :type type_constraint: :class:`TypeConstraint`
  :param mapping: A mapping from keys to values satisfying the type constraint or else strings
                  encoding the address such values should be resolved from; aka. 'pointers'.
  :type mapping: :class:`collections.Mapping`
  :returns: A dict whose values satisfy the type constraint directly or else are :class:`Addressed`
            pointers to values to resolve later.
  :rtype: dict
  """
  return {k: addressable(type_constraint, v) for k, v in mapping.items()} if mapping else {}
