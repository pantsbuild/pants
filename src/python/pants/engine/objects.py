# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
import sys
from abc import ABC, abstractmethod
from collections import namedtuple

from pants.util.memo import memoized_classmethod
from pants.util.objects import Exactly, TypedCollection, datatype


class SerializationError(Exception):
  """Indicates an error serializing an object."""


# TODO: Likely no longer necessary, due to the laziness of the product graph.
class Resolvable(ABC):
  """Represents a resolvable object."""

  @property
  @abstractmethod
  def address(self):
    """Return the opaque address descriptor that this resolvable resolves."""

  @abstractmethod
  def resolve(self):
    """Resolve and return the resolvable object."""


def _unpickle_serializable(serializable_class, kwargs):
  # A pickle-compatible top-level function for custom unpickling of Serializables.
  return serializable_class(**kwargs)


class Locatable(ABC):
  """Marks a class whose constructor should receive its spec_path relative to the build root.

  Locatable objects will be passed a `spec_path` constructor kwarg that indicates where they
  were parsed. If the object also has a `name` (not all do), then these two fields can be
  combined into an Address.
  """


class SerializablePickle(namedtuple('CustomPickle', ['unpickle_func', 'args'])):
  """A named tuple to help the readability of the __reduce__ protocol.

  See: https://docs.python.org/2.7/library/pickle.html#pickling-and-unpickling-extension-types
  """

  @classmethod
  def create(cls, serializable_instance):
    """Return a tuple that implements the __reduce__ pickle protocol for serializable_instance."""
    if not Serializable.is_serializable(serializable_instance):
      raise ValueError('Can only create pickles for Serializable objects, given {} of type {}'
                       .format(serializable_instance, type(serializable_instance).__name__))
    return cls(unpickle_func=_unpickle_serializable,
               args=(type(serializable_instance), serializable_instance._asdict()))


class Serializable(ABC):
  """Marks a class that can be serialized into and reconstituted from python builtin values.

  Also provides support for the pickling protocol out of the box.
  """

  @staticmethod
  def is_serializable(obj):
    """Return `True` if the given object conforms to the Serializable protocol.

    :rtype: bool
    """
    if inspect.isclass(obj):
      return Serializable.is_serializable_type(obj)
    return isinstance(obj, Serializable) or hasattr(obj, '_asdict')

  @staticmethod
  def is_serializable_type(type_):
    """Return `True` if the given type's instances conform to the Serializable protocol.

    :rtype: bool
    """
    if not inspect.isclass(type_):
      return Serializable.is_serializable(type_)
    return issubclass(type_, Serializable) or hasattr(type_, '_asdict')

  @abstractmethod
  def _asdict(self):
    """Return a dict mapping this class' properties.

    To meet the contract of a serializable the constructor must accept all the properties returned
    here as constructor parameters; ie the following must be true::

    >>> s = Serializable(...)
    >>> Serializable(**s._asdict()) == s

    Additionally the dict must also contain nothing except Serializables, python primitive values,
    ie: dicts, lists, strings, numbers, bool values, etc or Resolvables that resolve to Serilizables
    or primitive values.

    Any :class:`collections.namedtuple` satisfies the Serializable contract automatically via duck
    typing if it is composed of only primitive python values or Serializable values.
    """

  def __reduce__(self):
    # We implement __reduce__ to steer the pickling process away from __getattr__ scans.  This is
    # both more direct - we know where our instance data lives - and it notably allows __getattr__
    # implementations by Serializable subclasses.  Without the __reduce__, __getattr__ is rendered
    # unworkable since it causes pickle failures.
    # See the note at the bottom of this section:
    # https://docs.python.org/2.7/library/pickle.html#pickling-and-unpickling-normal-class-instances
    return SerializablePickle.create(self)


class SerializableFactory(ABC):
  """Creates :class:`Serializable` objects."""

  @abstractmethod
  def create(self):
    """Return a serializable object.

    :rtype: :class:`Serializable`
    """


class ValidationError(Exception):
  """Indicates invalid fields on an object."""

  def __init__(self, identifier, message):
    """Creates a validation error pertaining to the identified invalid object.

    :param object identifier: Any object whose string representation identifies the invalid object
                              that led to this validation error.
    :param string message: A message describing the invalid Struct field.
    """
    super().__init__('Failed to validate {id}: {msg}'
                                          .format(id=identifier, msg=message))


class Validatable(ABC):
  """Marks a class whose instances should validated post-construction."""

  @abstractmethod
  def validate(self):
    """Check that this object's fields are valid.

    :raises: :class:`ValidationError` if this object is invalid.
    """


class Collection:
  """Constructs classes representing collections of objects of a particular type.

  The produced class will expose its values under a field named dependencies - this is a stable API
  which may be consumed e.g. over FFI from the engine.

  Python consumers of a Collection should prefer to use its standard iteration API.

  Note that elements of a Collection are type-checked upon construction.
  """

  @memoized_classmethod
  def of(cls, *element_types):
    union = '|'.join(element_type.__name__ for element_type in element_types)
    type_name = '{}.of({})'.format(cls.__name__, union)
    type_checked_collection_class = datatype([
      # Create a datatype with a single field 'dependencies' which is type-checked on construction
      # to be a collection containing elements of only the exact `element_types` specified.
      ('dependencies', TypedCollection(Exactly(*element_types)))
    ], superclass_name=cls.__name__)
    supertypes = (cls, type_checked_collection_class)
    properties = {'element_types': element_types}
    collection_of_type = type(type_name, supertypes, properties)

    # Expose the custom class type at the module level to be pickle compatible.
    setattr(sys.modules[cls.__module__], type_name, collection_of_type)

    return collection_of_type

  def __iter__(self):
    return iter(self.dependencies)

  def __bool__(self):
    return bool(self.dependencies)
