# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import inspect
import sys
from abc import abstractmethod
from functools import update_wrapper

import six

from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.objects import Resolvable, Serializable
from pants.util.memo import memoized
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Collection(object):
  """
  Singleton Collection Type. The ambition is to gain native support for flattening,
  so methods like <pants.engine.fs.merge_files> won't have to be defined separately.
  Related to: https://github.com/pantsbuild/pants/issues/3169
  """

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


Addresses = Collection.of(Address)


class BuildFileAddresses(Collection.of(BuildFileAddress)):
  @property
  def addresses(self):
    """Converts the BuildFileAddress objects in this collection to Address objects."""
    return [bfa.to_address() for bfa in self.dependencies]


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


class NotSerializableError(TypeError):
  """Indicates an addressable descriptor is illegally installed in a non-Serializable type."""


class MutationError(AttributeError):
  """Indicates an illegal attempt to mutate an addressable attribute that already has a value."""


class TypeConstraintError(TypeError):
  """Indicates a :class:`TypeConstraint` violation."""


class AddressableDescriptor(object):
  """A data descriptor for fields containing one or more addressable items.

  An addressable descriptor has lifecycle expectations tightly coupled with the contract of
  Serializable objects and the 2-phase hydration of AddressMap.parse, Graph.resolve.

  Decorated accessors are write-once, and then read-only.  They are intended to be written in a
  constructor such that objects containing them have immutable semantics. In other words, the
  descriptor is intended to be used like a type-checked `@property` with possibly lazily resolved
  values.

  The written value is type-checked against a :class:`TypeConstraint` and can only be one of 3
  types:

  1. An opaque string address.
  2. A Resolvable for the address that, when resolved, will meet the type constraint.
  3. A concrete value that meets the type constraint.

  The 1st type, an opaque string address, is also the type associated with the 1st stage of the
  2-stage lifecycle of Serializable objects containing addressable values.  In the second and final
  stage, the Serializable object is re-constructed with addressable values of the second or third
  types; ie: reconstructed with either resolvables or concrete values in place of the first stage
  address.

  Two affordances are made in type constraint handling:

  1. Either a :class:`TypeConstraint` instance can be given if the type constraint is fully known or
     else a type constraint class can be given if the type constraint should apply to the type of
     the enclosing class.  This is useful for declaring an addressable property in a baseclass that
     should be type-constrained based on the type of the derived class.
  2. Decorators for addressables (see `addressable`, `addressable_list` and `addressable_dict`)
     allow wrapping of either class functions - typical - or @property descriptors.  The property
     descriptor case sets up an idiom for recursive addressables.  The idiom looks like:

     >>> class Thing(Struct):
     ...   def __init__(self, thing):
     ...     super(Thing, self).__init__()
     ...     self.thing = thing
     ...   @property
     ...   def parent(self):
     ...     '''Return this thing's parent.
     ...
     ...     :rtype: :class:`Thing`
     ...     '''
     ...
     >>> Thing.parent = addressable(Exactly(Thing))(Thing.parent)

     Here the `Thing.parent` property is re-assigned with a type-constrained addressable descriptor
     after the class is defined so the class can be referred to in the type constraint.
  """
  _descriptors = set()

  @classmethod
  def is_addressable(cls, obj, key):
    """Return `True` if the given attribute of `obj` is an addressable attribute.

    :param obj: The object to inspect.
    :param string key: The name of the property on `obj` to check.
    """
    return (type(obj), key) in cls._descriptors

  @classmethod
  def _register(cls, obj, descriptor):
    cls._descriptors.add((type(obj), descriptor._name))

  def __init__(self, name, type_constraint):
    self._name = name
    self._type_constraint = type_constraint

  def __set__(self, instance, value):
    if not Serializable.is_serializable(instance):
      raise NotSerializableError('The addressable descriptor {} can only be applied to methods or '
                                 'properties of Serializable objects, applied to method {} of '
                                 'type {}'.format(type(self).__name__,
                                                  self._name,
                                                  type(instance).__name__))

    instance_dict = instance._asdict()
    if self._name in instance_dict:
      raise MutationError('Attribute {} of {} has already been set to {}, rejecting attempt to '
                          're-set with {}'.format(self._name,
                                                  instance,
                                                  instance_dict[self._name],
                                                  value))

    value = self._checked_value(instance, value)

    self._register(instance, self)

    # We mutate the instance dict, which is only OK if used in the conventional idiom of setting
    # the value via this data descriptor in the instance's constructor.
    instance_dict[self._name] = value

  def __get__(self, instance, unused_owner_type=None):
    # We know instance is a Serializable from the type-checking done in set.
    value = instance._asdict()[self._name]
    return self._resolve_value(instance, value)

  def _get_type_constraint(self, instance):
    if inspect.isclass(self._type_constraint):
      return self._type_constraint(type(instance))
    else:
      return self._type_constraint

  def _checked_value(self, instance, value):
    # We allow five forms of value:
    # 0. None.
    # 1. An opaque (to us) address pointing to a value that can be resolved by external
    #    means.
    # 2. A `Resolvable` value that we can lazily resolve and type-check in `__get__`.
    # 3. A concrete instance that meets our type constraint.
    # 4. A dict when our type constraint has exactly one Serializable subject type - we convert the
    #    dict into an instance of that type.
    if value is None:
      return None

    if isinstance(value, (six.string_types, Address, Resolvable)):
      return value

    # Support untyped dicts that we deserialize on-demand here into the required type.
    # This feature allows for more brevity in the JSON form (local type inference) and an alternate
    # construction style in the python forms.
    type_constraint = self._get_type_constraint(instance)
    if (isinstance(value, dict) and
        len(type_constraint.types) == 1 and
        Serializable.is_serializable_type(type_constraint.types[0])):
      if not value:
        # TODO(John Sirois): Is this the right thing to do?  Or should an empty serializable_type
        # be constructed?
        return None  # {} -> None.
      else:
        serializable_type = type_constraint.types[0]
        return serializable_type(**value)

    if not type_constraint.satisfied_by(value):
      raise TypeConstraintError('Got {} of type {} for {} attribute of {} but expected {!r}'
                                .format(value,
                                        type(value).__name__,
                                        self._name,
                                        instance,
                                        type_constraint))
    return value

  def _resolve_value(self, instance, value):
    if not isinstance(value, Resolvable):
      # The value is concrete which means we type-checked on set so no need to do so again, its a
      # raw address string or an instance that satisfies our type constraint.
      return value
    else:
      resolved_value = value.resolve()
      type_constraint = self._get_type_constraint(instance)
      if not type_constraint.satisfied_by(resolved_value):
        raise TypeConstraintError('The value resolved from {} did not meet the type constraint of '
                                  '{!r} for the {} property of {}: {}'
                                  .format(value.address,
                                          type_constraint,
                                          self._name,
                                          instance,
                                          resolved_value))
      return resolved_value


def _addressable_wrapper(addressable_descriptor, type_constraint):
  def wrapper(func):
    # We allow for wrapping property objects to support the following idiom for defining recursive
    # addressables:
    #
    # class Thing(Struct):
    #   def __init__(self, thing):
    #      super(Thing, self).__init__()
    #      self.thing = thing
    #
    #   @property
    #   def parent(self):
    #     """Return this thing's parent.
    #
    #     :rtype: :class:`Thing`
    #     """"
    #
    # Thing.parent = addressable(Exactly(Thing))(Thing.parent)
    func = func.fget if isinstance(func, property) else func

    addressable_accessor = addressable_descriptor(func.__name__, type_constraint)
    return update_wrapper(addressable_accessor, func)
  return wrapper


def addressable(type_constraint):
  """Return an addressable attribute for Serializable classes.

  The attribute should have no implementation (it will be ignored), but can carry a docstring.
  The implementation is provided by this wrapper.  Idiomatic use assigns the value, which can
  either be an opaque address string or a resolved value that meets the type constraint, in the
  constructor::

  >>> class Employee(Serializable):
  ...   def __init__(self, person):
  ...     self.person = person
  ...   @addressable(SubclassesOf(Person))
  ...   def person(self):
  ...     '''The person that is this employee.'''

  Addressable attributes are only assignable once, so this pattern yields an immutable `Employee`
  whose `person` attribute is either a `Person` instance or
  :class:`pants.engine.objects.Resolvable` person or else a string address pointing to one.

  See :class:`AddressableDescriptor` for more details.

  :param type_constraint: The type constraint the value must satisfy.
  :type type_constraint: :class:`TypeConstraint`
  """
  return _addressable_wrapper(AddressableDescriptor, type_constraint)


class AddressableList(AddressableDescriptor):
  def _checked_value(self, instance, value):
    if value is None:
      return None

    if not isinstance(value, collections.MutableSequence):
      raise TypeError('The {} property of {} must be a list, given {} of type {}'
                      .format(self._name, instance, value, type(value).__name__))
    return [super(AddressableList, self)._checked_value(instance, v) for v in value]

  def _resolve_value(self, instance, value):
    return [super(AddressableList, self)._resolve_value(instance, v)
            for v in value] if value else []


def addressable_list(type_constraint):
  """Marks a list's values as satisfying a given type constraint.

  Some (or all) elements of the list may be :class:`pants.engine.objects.Resolvable` elements
  to resolve later.

  See :class:`AddressableDescriptor` for more details.

  :param type_constraint: The type constraint the list's values must all satisfy.
  :type type_constraint: :class:`TypeConstraint`
  """
  return _addressable_wrapper(AddressableList, type_constraint)


class AddressableDict(AddressableDescriptor):
  def _checked_value(self, instance, value):
    if value is None:
      return None

    if not isinstance(value, collections.MutableMapping):
      raise TypeError('The {} property of {} must be a dict, given {} of type {}'
                      .format(self._name, instance, value, type(value).__name__))
    return {k: super(AddressableDict, self)._checked_value(instance, v) for k, v in value.items()}

  def _resolve_value(self, instance, value):
    return {k: super(AddressableDict, self)._resolve_value(instance, v)
            for k, v in value.items()} if value else {}


def addressable_dict(type_constraint):
  """Marks a dicts's values as satisfying a given type constraint.

  Some (or all) values in the dict may be :class:`pants.engine.objects.Resolvable` values to
  resolve later.

  See :class:`AddressableDescriptor` for more details.

  :param type_constraint: The type constraint the dict's values must all satisfy.
  :type type_constraint: :class:`TypeConstraint`
  """
  return _addressable_wrapper(AddressableDict, type_constraint)


# TODO(John Sirois): Move variants into Address 1st class as part of merging the engine/exp
# into the mainline (if they survive).
# TODO: Variants currently require an explicit name (and thus a `:`) in order to parse correctly.
def strip_variants(address):
  """Return a copy of the given address with the variants (if any) stripped from the name.

  :rtype: :class:`pants.build_graph.address.Address`
  """
  address, _ = parse_variants(address)
  return address


def _extract_variants(address, variants_str):
  """Return the variants (if any) represented by the given variants_str.

  :returns: The variants or else `None` if there are none.
  :rtype: tuple of tuples (key, value) strings
  """
  def entries():
    for entry in variants_str.split(','):
      key, _, value = entry.partition('=')
      if not key or not value:
        raise ValueError('Invalid variants after the @ in: {}'.format(address))
      yield (key, value)
  return tuple(entries())


def parse_variants(address):
  target_name, at_sign, variants_str = address.target_name.partition('@')
  if not at_sign:
    return address, None
  variants = _extract_variants(address, variants_str) if variants_str else None
  if isinstance(address, BuildFileAddress):
    normalized_address = BuildFileAddress(rel_path=address.rel_path, target_name=target_name)
  else:
    normalized_address = Address(spec_path=address.spec_path, target_name=target_name)
  return normalized_address, variants
