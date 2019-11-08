# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod


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
