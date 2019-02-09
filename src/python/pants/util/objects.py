# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import abstractmethod
from builtins import zip
from collections import namedtuple

from twitter.common.collections import OrderedSet

from pants.util.collections_abc_backport import Iterable, OrderedDict
from pants.util.memo import memoized, memoized_classproperty
from pants.util.meta import AbstractClass, classproperty


class TypeCheckError(TypeError):

  # TODO: make some wrapper exception class to make this kind of
  # prefixing easy (maybe using a class field format string?).
  def __init__(self, type_name, msg, *args, **kwargs):
    formatted_msg = "type check error in class {}: {}".format(type_name, msg)
    super(TypeCheckError, self).__init__(formatted_msg, *args, **kwargs)


class TypedDatatypeInstanceConstructionError(TypeCheckError):
  """Raised when a datatype()'s fields fail a type check upon construction."""


class TypeCheckError(TypeError):

  # TODO: make some wrapper exception class to make this kind of
  # prefixing easy (maybe using a class field format string?).
  def __init__(self, type_name, msg, *args, **kwargs):
    formatted_msg = "type check error in class {}: {}".format(type_name, msg)
    super(TypeCheckError, self).__init__(formatted_msg, *args, **kwargs)


class TypedDatatypeInstanceConstructionError(TypeCheckError):
  """Raised when a datatype()'s fields fail a type check upon construction."""


# TODO: create a mixin which declares/implements the methods we define on the generated class in
# datatype() and enum() to decouple the class's logic from the way it's created. This may also make
# migration to python 3 dataclasses as per #7074 easier.
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

  class DataType(namedtuple_cls):
    @classproperty
    def type_check_error_type(cls):
      """The exception type to use in make_type_error()."""
      return TypedDatatypeInstanceConstructionError

    @classmethod
    def make_type_error(cls, msg, *args, **kwargs):
      """A helper method to generate an exception type for type checking errors.

      This method uses `cls.type_check_error_type` to ensure that type checking errors can be caught
      with a reliable exception type. The type returned by `cls.type_check_error_type` should ensure
      that the exception messages are prefixed with enough context to be useful and *not* confusing.
      """
      return cls.type_check_error_type(cls.__name__, msg, *args, **kwargs)

    def __new__(cls, *args, **kwargs):
      # TODO: Ideally we could execute this exactly once per `cls` but it should be a
      # relatively cheap check.
      if not hasattr(cls.__eq__, '_eq_override_canary'):
        raise cls.make_type_error('Should not override __eq__.')

      try:
        this_object = super(DataType, cls).__new__(cls, *args, **kwargs)
      except TypeError as e:
        raise cls.make_type_error(
          "error in namedtuple() base constructor: {}".format(e))

      # TODO: Make this kind of exception pattern (filter for errors then display them all at once)
      # more ergonomic.
      type_failure_msgs = []
      for field_name, field_constraint in fields_with_constraints.items():
        field_value = getattr(this_object, field_name)
        try:
          field_constraint.validate_satisfied_by(field_value)
        except TypeConstraintError as e:
          type_failure_msgs.append(
            "field '{}' was invalid: {}".format(field_name, e))
      if type_failure_msgs:
        raise cls.make_type_error(
          'errors type checking constructor arguments:\n{}'
          .format('\n'.join(type_failure_msgs)))

      return this_object

    def __eq__(self, other):
      if self is other:
        return True

      # Compare types and fields.
      if type(self) != type(other):
        return False
      # Explicitly return super.__eq__'s value in case super returns NotImplemented
      return super(DataType, self).__eq__(other)
    # We define an attribute on the `cls` level definition of `__eq__` that will allow us to detect
    # that it has been overridden.
    __eq__._eq_override_canary = None

    def __ne__(self, other):
      return not (self == other)

    def __hash__(self):
      return super(DataType, self).__hash__()

    # NB: As datatype is not iterable, we need to override both __iter__ and all of the
    # namedtuple methods that expect self to be iterable.
    def __iter__(self):
      raise TypeError("'{}' object is not iterable".format(type(self).__name__))

    def _super_iter(self):
      return super(DataType, self).__iter__()

    def _asdict(self):
      '''Return a new OrderedDict which maps field names to their values'''
      return OrderedDict(zip(self._fields, self._super_iter()))

    def _replace(_self, **kwds):
      '''Return a new datatype object replacing specified fields with new values'''
      field_dict = _self._asdict()
      field_dict.update(**kwds)
      return type(_self)(**field_dict)

    copy = _replace

    # NB: it is *not* recommended to rely on the ordering of the tuple returned by this method.
    def __getnewargs__(self):
      '''Return self as a plain tuple.  Used by copy and pickle.'''
      return tuple(self._super_iter())

    def __repr__(self):
      args_formatted = []
      for field_name in field_names:
        field_value = getattr(self, field_name)
        args_formatted.append("{}={!r}".format(field_name, field_value))
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
  try:  # Python3
    return type(superclass_name, (DataType,), {})
  except TypeError:  # Python2
    return type(superclass_name.encode('utf-8'), (DataType,), {})


class EnumVariantSelectionError(TypeCheckError):
  """Raised when an invalid variant for an enum() is constructed or matched against."""


def enum(*args):
  """A datatype which can take on a finite set of values. This method is experimental and unstable.

  Any enum subclass can be constructed with its create() classmethod. This method will use the first
  element of `all_values` as the default value, but enum classes can override this behavior by
  setting `default_value` in the class body.

  NB: Relying on the `field_name` directly is discouraged in favor of using
  resolve_for_enum_variant() in Python code. The `field_name` argument is exposed to make enum
  instances more readable when printed, and to allow code in another language using an FFI to
  reliably extract the value from an enum instance.

  :param string field_name: A string used as the field for the datatype. This positional argument is
                            optional, and defaults to 'value'. Note that `enum()` does not yet
                            support type checking as with `datatype()`.
  :param Iterable all_values: A nonempty iterable of objects representing all possible values for
                              the enum.  This argument must be a finite, non-empty iterable with
                              unique values.
  :raises: :class:`ValueError`
  """
  if len(args) == 1:
    field_name = 'value'
    all_values, = args
  elif len(args) == 2:
    field_name, all_values = args
  else:
    raise ValueError("enum() accepts only 1 or 2 args! args = {!r}".format(args))

  # This call to list() will eagerly evaluate any `all_values` which would otherwise be lazy, such
  # as a generator.
  all_values_realized = list(all_values)
  # `OrderedSet` maintains the order of the input iterable, but is faster to check membership.
  allowed_values_set = OrderedSet(all_values_realized)

  if len(allowed_values_set) == 0:
    raise ValueError("all_values must be a non-empty iterable!")
  elif len(allowed_values_set) < len(all_values_realized):
    raise ValueError("When converting all_values ({}) to a set, at least one duplicate "
                     "was detected. The unique elements of all_values were: {}."
                     .format(all_values_realized, list(allowed_values_set)))

  class ChoiceDatatype(datatype([field_name])):
    default_value = next(iter(allowed_values_set))

    # Overriden from datatype() so providing an invalid variant is catchable as a TypeCheckError,
    # but more specific.
    type_check_error_type = EnumVariantSelectionError

    # Overriden from datatype() so providing an invalid variant is catchable as a TypeCheckError,
    # but more specific.
    type_check_error_type = EnumVariantSelectionError

    @memoized_classproperty
    def _singletons(cls):
      """Generate memoized instances of this enum wrapping each of this enum's allowed values.

      NB: The implementation of enum() should use this property as the source of truth for allowed
      values and enum instances from those values.
      """
      return OrderedDict((value, cls._make_singleton(value)) for value in allowed_values_set)

    @classmethod
    def _make_singleton(cls, value):
      """
      We convert uses of the constructor to call create(), so we then need to go around __new__ to
      bootstrap singleton creation from datatype()'s __new__.
      """
      return super(ChoiceDatatype, cls).__new__(cls, value)

    @classproperty
    def _allowed_values(cls):
      """The values provided to the enum() type constructor, for use in error messages."""
      return list(cls._singletons.keys())

    def __new__(cls, value):
      """Forward `value` to the .create() factory method.

      The .create() factory method is preferred, but forwarding the constructor like this allows us
      to use the generated enum type both as a type to check against with isinstance() as well as a
      function to create instances with. This makes it easy to use as a pants option type.
      """
      return cls.create(value)

    @classmethod
    def create(cls, *args, **kwargs):
      """Create an instance of this enum, using the default value if specified.

      :param value: Use this as the enum value. If `value` is an instance of this class, return it,
                    otherwise it is checked against the enum's allowed values. This positional
                    argument is optional, and if not specified, `cls.default_value` is used.
      :param bool none_is_default: If this is True, a None `value` is converted into
                                   `cls.default_value` before being checked against the enum's
                                   allowed values.
      """
      none_is_default = kwargs.pop('none_is_default', False)
      if kwargs:
        raise ValueError('unrecognized keyword arguments for {}.create(): {!r}'
                         .format(cls.__name__, kwargs))

      if len(args) == 0:
        value = cls.default_value
      elif len(args) == 1:
        value = args[0]
        if none_is_default and value is None:
          value = cls.default_value
      else:
        raise ValueError('{}.create() accepts 0 or 1 positional args! *args = {!r}'
                         .format(cls.__name__, args))

      # If we get an instance of this enum class, just return it. This means you can call .create()
      # on an allowed value for the enum, or an existing instance of the enum.
      if isinstance(value, cls):
        return value

      if value not in cls._singletons:
        raise cls.make_type_error(
          "Value {!r} for '{}' must be one of: {!r}."
          .format(value, field_name, cls._allowed_values))
      return cls._singletons[value]

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
      match_for_variant = mapping[getattr(self, field_name)]
      return match_for_variant

    @classmethod
    def iterate_enum_variants(cls):
      """Iterate over all instances of this enum, in the declared order.

      NB: This method is exposed for testing enum variants easily. resolve_for_enum_variant() should
      be used for performing conditional logic based on an enum instance's value.
      """
      # TODO(#7232): use this method to register attributes on the generated type object for each of
      # the singletons!
      return cls._singletons.values()

  return ChoiceDatatype

# TODO(#7233): allow usage of the normal register() by using an enum class as the `type` argument!
def register_enum_option(register, enum_cls, *args, **kwargs):
  """A helper method for declaring a pants option from an `enum()`."""
  default_value = kwargs.pop('default', enum_cls.default_value)
  register(*args, choices=enum_cls._allowed_values, default=default_value, **kwargs)


# TODO: make these members of the `TypeConstraint` class!
class TypeConstraintError(TypeError):
  """Indicates a :class:`TypeConstraint` violation."""


class TypeConstraint(AbstractClass):
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

  # TODO: make an @abstract_classproperty decorator to do this boilerplate!
  @classproperty
  def _variance_symbol(cls):
    """This is propagated to the the `TypeConstraint` constructor."""
    raise NotImplementedError('{} must implement the _variance_symbol classproperty!'
                              .format(cls.__name__))

  def __init__(self, *types):
    """Creates a type constraint based on some logic to match the given types.

    NB: A `TypeOnlyConstraint` implementation should ensure that the type constraint is satisfied as
    a whole if satisfied for at least one of the given `types`.

    :param type *types: The types this constraint will match in some way.
    """

    if not types:
      raise ValueError('Must supply at least one type')
    if any(not isinstance(t, type) for t in types):
      raise TypeError('Supplied types must be types. {!r}'.format(types))

    if len(types) == 1:
      type_list = types[0].__name__
    else:
      type_list = ' or '.join(t.__name__ for t in types)
    description = '{}({})'.format(type(self).__name__, type_list)

    super(TypeOnlyConstraint, self).__init__(description=description)

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

  _iterable_constraint = SubclassesOf(Iterable)

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

    super(TypedCollection, self).__init__(description=description)

  # TODO: consider making this a private method of TypeConstraint, as it now duplicates the logic in
  # self.validate_satisfied_by()!
  def satisfied_by(self, obj):
    if self._iterable_constraint.satisfied_by(obj):
      return all(self._constraint.satisfied_by(el) for el in obj)
    return False

  def make_collection_type_constraint_error(self, base_obj, el):
    base_error = self.make_type_constraint_error(el, self._constraint)
    return TypeConstraintError("in wrapped constraint {} matching iterable object {}: {}"
                               .format(self, base_obj, base_error))

  def validate_satisfied_by(self, obj):
    if self._iterable_constraint.satisfied_by(obj):
      for el in obj:
        if not self._constraint.satisfied_by(el):
          raise self.make_collection_type_constraint_error(obj, el)
      return obj

    base_iterable_error = self.make_type_constraint_error(obj, self._iterable_constraint)
    raise TypeConstraintError(
      "in wrapped constraint {}: {}".format(self, base_iterable_error))

  def __hash__(self):
    return hash((type(self), self._constraint))

  def __eq__(self, other):
    return type(self) == type(other) and self._constraint == other._constraint

  def __repr__(self):
    return ('{type_constraint_type}({constraint!r})'
            .format(type_constraint_type=type(self).__name__,
                    constraint=self._constraint))
