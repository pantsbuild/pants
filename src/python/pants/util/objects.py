# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import abstractmethod
from builtins import zip
from collections import namedtuple

from twitter.common.collections import OrderedSet

from pants.util.collections_abc_backport import Iterable, OrderedDict
from pants.util.memo import memoized_classproperty
from pants.util.meta import AbstractClass, classproperty


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
    @classmethod
    def make_type_error(cls, msg, *args, **kwargs):
      return TypeCheckError(cls.__name__, msg, *args, **kwargs)

    def __new__(cls, *args, **kwargs):
      # TODO: Ideally we could execute this exactly once per `cls` but it should be a
      # relatively cheap check.
      if not hasattr(cls.__eq__, '_eq_override_canary'):
        raise cls.make_type_error('Should not override __eq__.')

      # NB: `TypeConstraint#validate_satisfied_by()` can return a different result than its input if
      # a `wrapper_type` argument is provided to the base class constructor. Because `namedtuple` is
      # immutable, we have to do any modifications here. The extra work in this method which
      # duplicates the positional and keyword argument checking in `namedtuple` reduces a
      # significant amount of boilerplate when creating `datatype` objects which accept collections,
      # allowing the object's creator to pass in any type of collection as an argument and ensure
      # the object is still hashable (by converting it to a tuple). We can also improve the quality
      # of the argument checking error messages and ensure they are consistent across python
      # versions.
      if len(args) > len(field_names):
        raise cls.make_type_error(
          """\
too many positional arguments: {} arguments for {} fields!
args: {}
fields: {}"""
          .format(len(args), len(field_names), args, field_names))

      # Create a dictionary of the positional and keyword arguments.
      # NB: We use an OrderedDict() to ensure reproducible error messages.
      arg_dict = OrderedDict()
      selected_field_names = []
      for field_index, arg_value in enumerate(args):
        field_name = field_names[field_index]
        arg_dict[field_name] = arg_value
        selected_field_names.append(field_name)

      # Raise if an argument was specified positionally and with a keyword.
      overlapping_field_names = frozenset(selected_field_names) & frozenset(kwargs.keys())
      if overlapping_field_names:
        raise cls.make_type_error(
          """\
arguments were specified positionally and by keyword: {}!
args: {}
kwargs: {}""".format(list(overlapping_field_names), args, kwargs))

      # The arguments were non-overlapping, so we can safely populate the arg dict.
      arg_dict.update(kwargs)

      # Check that we don't have any unknown arguments *before* we perform type checking.
      unrecognized_args = frozenset(arg_dict.keys()) - frozenset(field_names)
      if unrecognized_args:
        raise cls.make_type_error("unrecognized arguments: {}".format(list(unrecognized_args)))
      # Check that we have specified all of the non-optional arguments.
      missing_args = frozenset(field_names) - frozenset(arg_dict.keys())
      if missing_args:
        raise cls.make_type_error("missing arguments: {}".format(list(missing_args)))

      # TODO: Make this kind of exception pattern (filter for errors then display them all at once)
      # more ergonomic.
      type_failure_msgs = []
      for arg_name, arg_value in arg_dict.items():
        field_constraint = fields_with_constraints.get(arg_name, None)
        if field_constraint:
          try:
            new_arg_val = field_constraint.validate_satisfied_by(arg_value)
          except TypeConstraintError as e:
            type_failure_msgs.append("field '{}' was invalid: {}".format(arg_name, e))
            new_arg_val = 'ERROR: {}'.format(e)
        else:
          new_arg_val = arg_value
        arg_dict[arg_name] = new_arg_val
      if type_failure_msgs:
        raise cls.make_type_error('\n'.join(type_failure_msgs))

      # NB: We haven't checked that we specified all of the non-optional arguments -- we let the
      # `namedtuple` constructor do that checking for us.
      try:
        this_object = super(DataType, cls).__new__(cls, **arg_dict)
      except TypeError as e:
        raise cls.make_type_error(e)

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


def enum(field_name, all_values):
  """A datatype which can take on a finite set of values. This method is experimental and unstable.

  Any enum subclass can be constructed with its create() classmethod. This method will use the first
  element of `all_values` as the enum value if none is specified.

  :param field_name: A string used as the field for the datatype. Note that enum does not yet
                     support type checking as with datatype.
  :param all_values: An iterable of objects representing all possible values for the enum.
                     NB: `all_values` must be a finite, non-empty iterable with unique values!
  """

  # This call to list() will eagerly evaluate any `all_values` which would otherwise be lazy, such
  # as a generator.
  all_values_realized = list(all_values)
  # `OrderedSet` maintains the order of the input iterable, but is faster to check membership.
  allowed_values_set = OrderedSet(all_values_realized)

  if len(allowed_values_set) < len(all_values_realized):
    raise ValueError("When converting all_values ({}) to a set, at least one duplicate "
                     "was detected. The unique elements of all_values were: {}."
                     .format(all_values_realized, allowed_values_set))

  class ChoiceDatatype(datatype([field_name])):
    allowed_values = allowed_values_set
    default_value = next(iter(allowed_values))

    @memoized_classproperty
    def _singletons(cls):
      """Generate memoized instances of this enum wrapping each of this enum's allowed values."""
      return { value: cls(value) for value in cls.allowed_values }

    @classmethod
    def _check_value(cls, value):
      if value not in cls.allowed_values:
        raise cls.make_type_error(
          "Value {!r} for '{}' must be one of: {!r}."
          .format(value, field_name, cls.allowed_values))

    @classmethod
    def create(cls, value=None):
      # If we get an instance of this enum class, just return it. This means you can call .create()
      # on None, an allowed value for the enum, or an existing instance of the enum.
      if isinstance(value, cls):
        return value

      # Providing an explicit value that is not None will *not* use the default value!
      if value is None:
        value = cls.default_value

      # We actually circumvent the constructor in this method due to the cls._singletons
      # memoized_classproperty, but we want to raise the same error, so we move checking into a
      # common method.
      cls._check_value(value)

      return cls._singletons[value]

    def __new__(cls, *args, **kwargs):
      this_object = super(ChoiceDatatype, cls).__new__(cls, *args, **kwargs)

      field_value = getattr(this_object, field_name)

      cls._check_value(field_value)

      return this_object

  return ChoiceDatatype


class TypedDatatypeClassConstructionError(Exception):

  # TODO: make some wrapper exception class to make this kind of
  # prefixing easy (maybe using a class field format string?).
  def __init__(self, type_name, msg, *args, **kwargs):
    full_msg =  "error: while trying to generate typed datatype {}: {}".format(
      type_name, msg)
    super(TypedDatatypeClassConstructionError, self).__init__(
      full_msg, *args, **kwargs)


class TypedDatatypeInstanceConstructionError(TypeError):

  def __init__(self, type_name, msg, *args, **kwargs):
    full_msg = "error: in constructor of type {}: {}".format(type_name, msg)
    super(TypedDatatypeInstanceConstructionError, self).__init__(
      full_msg, *args, **kwargs)


class TypeCheckError(TypedDatatypeInstanceConstructionError):

  def __init__(self, type_name, msg, *args, **kwargs):
    formatted_msg = "type check error:\n{}".format(msg)
    super(TypeCheckError, self).__init__(
      type_name, formatted_msg, *args, **kwargs)


# TODO: make these members of the `TypeConstraint` class!
class TypeConstraintError(TypeError):
  """Indicates a :class:`TypeConstraint` violation."""


class TypeConstraint(AbstractClass):
  """Represents a type constraint.

  Not intended for direct use; instead, use one of :class:`SuperclassesOf`, :class:`Exactly` or
  :class:`SubclassesOf`.
  """

  def __init__(self, variance_symbol, wrapper_type, description):
    """Creates a type constraint centered around the given types.

    The type constraint is satisfied as a whole if satisfied for at least one of the given types.

    :param type *types: The focus of this type constraint.
    :param str description: A description for this constraint if the list of types is too long.
    """
    assert(variance_symbol)
    if wrapper_type is not None:
      if not isinstance(wrapper_type, type):
        raise TypeError("wrapper_type must be a type! was: {} (type '{}')"
                        .format(wrapper_type, type(wrapper_type).__name__))
    self._variance_symbol = variance_symbol
    self._wrapper_type = wrapper_type
    self._description = description

  @abstractmethod
  def satisfied_by(self, obj):
    """Return `True` if the given object satisfies this type constraint.

    :rtype: bool
    """

  def validate_satisfied_by(self, obj):
    """Return some version of `obj` if the object satisfies this type constraint, or raise.

    If this `TypeConstraint` instance provided a `wrapper_type` to the base class constructor, the
    result will be of the type `self._wrapper_type`.

    :raises: `TypeConstraintError` if `obj` does not satisfy the constraint.
    """

    if self.satisfied_by(obj):
      if self._wrapper_type:
        return self._wrapper_type(obj)
      return obj

    raise TypeConstraintError(
      "value {!r} (with type {!r}) must satisfy this type constraint: {!r}."
      .format(obj, type(obj).__name__, self))

  def __ne__(self, other):
    return not (self == other)

  def __str__(self):
    return '{}{}'.format(self._variance_symbol, self._description)


class BasicTypeConstraint(TypeConstraint):
  """A `TypeConstraint` predicated only on the object's type."""

  # TODO: make an @abstract_classproperty decorator to do this boilerplate!
  @classproperty
  def _variance_symbol(cls):
    """This is propagated to the the `TypeConstraint` constructor."""
    raise NotImplementedError('{} must implement the _variance_symbol classproperty!'
                              .format(cls.__name__))

  def __init__(self, *types):
    """Creates a type constraint centered around the given types.

    The type constraint is satisfied as a whole if satisfied for at least one of the given types.

    :param type *types: The focus of this type constraint.
    :param str description: A description for this constraint if the list of types is too long.
    """

    if not types:
      raise ValueError('Must supply at least one type')
    if any(not isinstance(t, type) for t in types):
      raise TypeError('Supplied types must be types. {!r}'.format(types))

    if len(types) == 1:
      constrained_type = types[0].__name__
    else:
      constrained_type = '({})'.format(', '.join(t.__name__ for t in types))

    super(BasicTypeConstraint, self).__init__(
      variance_symbol=self._variance_symbol,
      wrapper_type=None,
      description=constrained_type)

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


class SuperclassesOf(BasicTypeConstraint):
  """Objects of the exact type as well as any super-types are allowed."""

  _variance_symbol = '-'

  def satisfied_by_type(self, obj_type):
    return any(issubclass(t, obj_type) for t in self._types)


class Exactly(BasicTypeConstraint):
  """Only objects of the exact type are allowed."""

  _variance_symbol = '='

  def satisfied_by_type(self, obj_type):
    return obj_type in self._types

  def graph_str(self):
    if len(self.types) == 1:
      return self.types[0].__name__
    else:
      return repr(self)


class SubclassesOf(BasicTypeConstraint):
  """Objects of the exact type as well as any sub-types are allowed."""

  _variance_symbol = '+'

  def satisfied_by_type(self, obj_type):
    return issubclass(obj_type, self._types)


class TypedCollection(TypeConstraint):
  """A `TypeConstraint` which accepts a BasicTypeConstraint and validates a collection."""

  @classmethod
  def _generate_variance_symbol(cls, constraint):
    return '[{}]'.format(constraint._variance_symbol)

  def __init__(self, constraint, wrapper_type=tuple):
    """
    :param BasicTypeConstraint constraint: ???
    :param type wrapper_type:
    """

    if not isinstance(constraint, BasicTypeConstraint):
      raise TypeError("constraint for collection must be a {}! was: {}"
                      .format(BasicTypeConstraint.__name__, constraint))
    self._constraint = constraint

    super(TypedCollection, self).__init__(
      variance_symbol=self._generate_variance_symbol(constraint),
      wrapper_type=wrapper_type,
      description=constraint._description)

  def satisfied_by(self, obj):
    if isinstance(obj, Iterable):
      return all(self._constraint.satisfied_by(el) for el in obj)
    return False

  def __hash__(self):
    return hash((type(self), self._constraint, self._wrapper_type))

  def __eq__(self, other):
    return type(self) == type(other) and self._constraint == other._constraint

  def __repr__(self):
    return ('{type_constraint_type}({constraint!r}, wrapper_type={wrapper_type})'
            .format(type_constraint_type=type(self).__name__,
                    constraint=self._constraint,
                    wrapper_type=self._wrapper_type.__name__))
