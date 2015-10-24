# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import MutableMapping, MutableSequence

from pants.engine.exp.addressable import SuperclassesOf, addressable, addressable_list
from pants.engine.exp.objects import Serializable, SerializableFactory, Validatable, ValidationError


class Configuration(Serializable, SerializableFactory, Validatable):
  """A serializable object describing some bit of build configuration.

  All build configuration data is composed of basic python builtin types and higher-level
  configuration objects that aggregate configuration data.  Configuration objects can carry a name
  in which case they become addressable and can be reused.
  """

  # Internal book-keeping fields to exclude from hash codes/equality checks.
  _SPECIAL_FIELDS = ('extends', 'merges', 'type_alias')

  def __init__(self, abstract=False, extends=None, merges=None, **kwargs):
    """Creates a new configuration data blob.

    By default configurations are anonymous (un-named), concrete (not `abstract`), and they neither
    inherit nor merge another configuration.

    Inheritance is allowed via the `extends` and `merges` channels.  An object inherits all
    attributes from the object it extends, overwriting any attributes in common with the extended
    object with its own.  The relationship is an "overlay".  For the merges, the same rules apply
    for as for extends working left to right such that the rightmost merges attribute will overwrite
    any similar attribute from merges to its left where the main object does not itself define the
    attribute.  The primary difference is in handling of lists and dicts.  These are merged and not
    over-written; again working from left to right with the main object's collection serving as the
    seed when present.

    A configuration can be semantically abstract without setting `abstract=True`. The `abstract`
    value can serve as documentation, or, for subclasses that provide an implementation for
    `validate_concrete`, it allows skipping validation for abstract instances.

    :param bool abstract: `True` to mark this configuration item as abstract, in which case no
                          validation is performed (see `validate_concrete`); `False` by default.
    :param extends: The configuration instance to inherit field values from.  Any shared fields are
                    over-written with this instances values.
    :type extends: An addressed or concrete configuration instance that is a type compatible with
                   this configuration or this configurations superclasses.
    :param merges: The configuration instances to merge this instances field values with.  Merging
                   is like extension except for containers, which are extended instead of replaced;
                   ie: any `dict` values are updated with this instances items and any `list` values
                   are extended with this instances items.
    :type merges: An addressed or concrete configuration instance that is a type compatible with
                  this configuration or this configurations superclasses.
    :param **kwargs: The configuration parameters.
    """
    self._kwargs = kwargs

    self._kwargs['abstract'] = abstract

    self.extends = extends
    self.merges = merges

    # Allow for configuration items that are directly constructed in memory.  These can have an
    # address directly assigned (vs. inferred from name + source file location) and we only require
    # that if they do, their name - if also assigned, matches the address.
    if self.address:
      target_name, _, config_specifier = self.address.target_name.partition('@')
      if self.name and self.name != target_name:
        self.report_validation_error('Address and name do not match! address: {}, name: {}'
                                     .format(self.address, self.name))
      self._kwargs['name'] = target_name

    self._hashable_key = None

  @property
  def name(self):
    """Return the name of this object, if any.

    In general configuration objects need not be named, in which case they are generally embedded
    objects; ie: attributes values of enclosing named configuration objects.  Any top-level
    configuration object, though, will carry a unique name (in the configuration object's enclosing
    namespace) that can be used to address it.

    :rtype: string
    """
    return self._kwargs.get('name')

  @property
  def address(self):
    """Return the address of this object, if any.

    In general configuration objects need not be identified by an address, in which case they are
    generally embedded objects; ie: attributes values of enclosing named configuration objects.
    Any top-level configuration object, though, will be identifiable via a unique address.

    :rtype: :class:`pants.build_graph.address.Address`
    """
    return self._kwargs.get('address')

  @property
  def type_alias(self):
    """Return the type alias this target was constructed via.

    For a target read from a BUILD file, this will be target alias, like 'java_library'.
    For a target constructed in memory, this will be the simple class name, like 'JavaLibrary'.

    The end result is that the type alias should be the most natural way to refer to this target's
    type to the author of the target instance.

    :rtype: string
    """
    return self._kwargs.get('type_alias', type(self).__name__)

  @property
  def abstract(self):
    """Return `True` if this object has been marked as abstract.

    Abstract objects are not validated. See: `validate_concrete`.

    :rtype: bool
    """
    return self._kwargs['abstract']

  # It only makes sense to inherit a subset of our own fields (we should not inherit new fields!),
  # our superclasses logically provide fields within this constrained set.
  # NB: Since `Configuration` is at base an ~unconstrained struct, a superclass does allow for
  # arbitrary and thus more fields to be defined than a subclass might logically support.  We
  # accept this hole in a trade for generally expected behavior when `Configuration` is subclassed
  # in the style of constructors with named parameters representing the full complete set of
  # expected parameters leaving **kwargs only for use by 'the system'; ie for `type_alias` and
  # `address` plumbing for example.
  #
  # Of note is the fact that we pass a constraint type and not a concrete constraint value.  This
  # tells addressable to use `SuperclassesOf([Configuration instance's type])`, which is what we
  # want.  Aka, for `ConfigurationSubclassA`, the constraint is
  # `SuperclassesOf(ConfigurationSubclassA)`.
  #
  @addressable(SuperclassesOf)
  def extends(self):
    """Return the object this object extends, if any.

    :rtype: :class:`Serializable`
    """

  @addressable_list(SuperclassesOf)
  def merges(self):
    """Return the objects this object merges in, if any.

    :rtype: list of :class:`Serializable`
    """

  def _asdict(self):
    return self._kwargs

  def _extract_inheritable_attributes(self, serializable):
    attributes = serializable._asdict().copy()

    # Allow for embedded objects inheriting from addressable objects - they should never inherit an
    # address and any top-level object inheriting will have its own address.
    attributes.pop('address', None)

    # We should never inherit special fields - these are for local book-keeping only.
    for field in self._SPECIAL_FIELDS:
      attributes.pop(field, None)

    return attributes

  def create(self):
    if not (self.extends or self.merges):
      return self

    attributes = {k: v for k, v in self._asdict().items()
                  if k not in self._SPECIAL_FIELDS and v is not None}

    if self.extends:
      for k, v in self._extract_inheritable_attributes(self.extends).items():
        attributes.setdefault(k, v)

    if self.merges:
      def merge(attrs):
        for k, v in attrs.items():
          if isinstance(v, MutableMapping):
            mapping = attributes.get(k, {})
            mapping.update(v)
            attributes[k] = mapping
          elif isinstance(v, MutableSequence):
            sequence = attributes.get(k, [])
            sequence.extend(v)
            attributes[k] = sequence
          else:
            attributes.setdefault(k, v)

      for merged in self.merges:
        merge(self._extract_inheritable_attributes(merged))

    configuration_type = type(self)
    return configuration_type(**attributes)

  def validate(self):
    if not self.abstract:
      self.validate_concrete()

  def report_validation_error(self, message):
    """Raises a properly identified validation error.

    :param string message: An error message describing the validation error.
    :raises: :class:`pants.engine.exp.objects.ValidationError`
    """
    raise ValidationError(self.address, message)

  def validate_concrete(self):
    """Subclasses can override to implement validation logic.

    The object will be fully hydrated state and it's guaranteed the object will be concrete, aka.
    not `abstract`.  If an error is found in the object's configuration, a validation error should
    be raised by calling `report_validation_error`.

    :raises: :class:`pants.engine.exp.objects.ValidationError`
    """

  def __getattr__(self, item):
    if item in self._kwargs:
      return self._kwargs[item]
    raise AttributeError('{} does not have attribute {!r}'.format(self, item))

  def _key(self):
    if self._hashable_key is None:
      if self.address:
        self._hashable_key = self.address
      else:
        def hashable(value):
          if isinstance(value, dict):
            return tuple(sorted((k, hashable(v)) for k, v in value.items()))
          elif isinstance(value, list):
            return tuple(hashable(v) for v in value)
          else:
            return value
        self._hashable_key = tuple(sorted((k, hashable(v)) for k, v in self._kwargs.items()
                                          if k not in self._SPECIAL_FIELDS))
    return self._hashable_key

  def __hash__(self):
    return hash(self._key())

  def __eq__(self, other):
    return isinstance(other, Configuration) and self._key() == other._key()

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    classname = type(self).__name__
    if self.address:
      return '{classname}(address={address})'.format(classname=classname,
                                                     address=self.address.reference())
    else:
      return '{classname}({args})'.format(classname=classname,
                                          args=', '.join(sorted('{}={!r}'.format(k, v)
                                                                for k, v in self._kwargs.items()
                                                                if v)))
