# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import MutableMapping, MutableSequence

from pants.engine.exp.addressable import (Exactly, SubclassesOf, SuperclassesOf, addressable,
                                          addressable_mapping, addressables)
from pants.engine.exp.objects import Serializable, SerializableFactory, Validatable, ValidationError


class Config(Serializable, SerializableFactory, Validatable):
  """A serializable object describing some bit of build configuration.

  All build configuration data is composed of basic python builtin types and higher-level config
  objects that aggregate configuration data.  Config objects can carry a name in which case they
  become addressable and can be reused.
  """

  # Internal book-keeping fields to exclude from hash codes/equality checks.
  _SPECIAL_FIELDS = ('extends', 'merges', 'typename')

  def __init__(self, abstract=False, extends=None, merges=None, **kwargs):
    """Creates a new configuration data blob.

    By default configurations are anonymous (un-named), concrete (not `abstract`), and they neither
    inherit nor merge another configuration.

    Inheritance is only allowed via one of the `extends` or `merges` channels, it is an error to
    specify both.  A configuration can be semantically abstract without setting `abstract=True`.
    The `abstract` value can serve as documentation, or, for subclasses that provide an
    implementation for `validate_concrete`, it allows skipping validation for abstract instances.

    :param bool abstract: `True` to mark this configuration item as abstract, in which case no
                          validation is performed (see `validate_concrete`); `False` by default.
    :param extends: The configuration instance to inherit field values from.  Any shared fields are
                    over-written with this instances values.
    :type extends: An addressed or concrete configuration instance that is a type compatible with
                   this configuration or this configurations superclasses.
    :param merges: The configuration instance to merge this instances field values with.  Merging is
                   like extension except for containers, which are extended instead of replaced; ie:
                   any `dict` values are updated with this instances items and any `list` values are
                   extended with this instances items.
    :type merges: An addressed or concrete configuration instance that is a type compatible with
                  this configuration or this configurations superclasses.
    :param **kwargs: The configuration parameters.
    """
    self._kwargs = kwargs

    self._kwargs['abstract'] = abstract

    # It only makes sense to inherit a subset of our own fields (we should not inherit new fields!),
    # our superclasses logically provide fields within this constrained set.
    # NB: Since Config is at base an ~unconstrained struct, a superclass does allow for arbitrary
    # and thus more fields to be defined than a subclass might logically support.  We accept this
    # hole in a trade for generally expected behavior when Config is subclassed in the style of
    # constructors with named parameters representing the full complete set of expected parameters
    # leaving **kwargs only for use by 'the system'; ie for `typename` and `address` plumbing for
    # example.
    self._kwargs['extends'] = addressable(SuperclassesOf(type(self)), extends)
    self._kwargs['merges'] = addressable(SuperclassesOf(type(self)), merges)

    # Allow for configuration items that are directly constructed in memory.  These can have an
    # address directly assigned (vs. inferred from name + source file location) and we only require
    # that if they do, their name - if also assigned, matches the address.
    if self.address:
      if self.name and self.name != self.address.target_name:
        self.report_validation_error('Address and name do not match! address: {}, name: {}'
                                     .format(self.address, self.name))
      self._kwargs['name'] = self.address.target_name

    self._hashable_key = None

  @property
  def name(self):
    """Return the name of this object, if any.

    In general config objects need not be named, in which case they are generally embedded objects;
    ie: attributes values of enclosing named config objects.  Any top-level config object though
    will carry a unique name (in the config object's enclosing namespace) that can be used to
    address it.

    :rtype: string
    """
    return self._kwargs.get('name')

  @property
  def address(self):
    """Return the address of this object, if any.

    In general config objects need not be identified by an address, in which case they are generally
    embedded objects; ie: attributes values of enclosing named config objects.  Any top-level config
    object though will be identifiable via a unique address.

    :rtype: :class:`pants.base.address.Address`
    """
    return self._kwargs.get('address')

  @property
  def typename(self):
    """Return the type name this target was constructed via.

    For a target read from a BUILD file, this will be target alias, like 'java_library'.
    For a target constructed in memory, this will be the simple class name, like 'JavaLibrary'.

    The end result is that the type alias should be the most natural way to refer to this target's
    type to the author of the target instance.

    :rtype: string
    """
    return self._kwargs.get('typename', type(self).__name__)

  @property
  def abstract(self):
    """Return `True` if this object has been marked as abstract.

    Abstract objects are not validated. See: `validate_concrete`.

    :rtype: bool
    """
    return self._kwargs['abstract']

  @property
  def extends(self):
    """Return the object this object extends, if any.

    :rtype: Serializable
    """
    return self._kwargs['extends']

  @property
  def merges(self):
    """Return the object this object merges in, if any.

    :rtype: Serializable
    """
    return self._kwargs['merges']

  def _asdict(self):
    return self._kwargs.copy()

  def _extract_inheritable_attributes(self, serializable):
    attributes = serializable._asdict()

    # Allow for un-named (embedded) objects inheriting from named objects
    attributes.pop('name', None)
    attributes.pop('address', None)

    # We should never inherit special fields - these are for local book-keeping only.
    for field in self._SPECIAL_FIELDS:
      attributes.pop(field, None)

    return attributes

  def create(self):
    if self.extends and self.merges:
      self.report_validation_error('Can only inherit from one object.  Both extension of {} and '
                                   'merging with {} were requested.'
                                   .format(self.extends.address, self.merges.address))

    if self.extends:
      attributes = self._extract_inheritable_attributes(self.extends)
      attributes.update((k, v) for k, v in self._asdict().items()
                        if k not in self._SPECIAL_FIELDS and v is not None)
      config_type = type(self)
      return config_type(**attributes)
    elif self.merges:
      attributes = self._extract_inheritable_attributes(self.merges)
      for k, v in self._asdict().items():
        if k not in self._SPECIAL_FIELDS:
          if isinstance(v, MutableMapping):
            attributes.setdefault(k, {}).update(v)
          elif isinstance(v, MutableSequence):
            attributes.setdefault(k, []).extend(v)
          elif v is not None:
            attributes[k] = v
      config_type = type(self)
      return config_type(**attributes)
    else:
      return self

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
    return self._kwargs[item]

  def _key(self):
    if self._hashable_key is None:
      self._hashable_key = sorted((k, v) for k, v in self._kwargs.items()
                                  if k not in self._SPECIAL_FIELDS)
    return self._hashable_key

  def __hash__(self):
    return hash(self._key())

  def __eq__(self, other):
    return isinstance(other, Config) and self._key() == other._key()

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    # TODO(John Sirois): Do something else here.  This is recursive and so printing a Node prints
    # its whole closure and will be too expensive and bewildering past simple example debugging.
    return '{classname}({args})'.format(classname=type(self).__name__,
                                        args=', '.join(sorted('{}={!r}'.format(k, v)
                                                              for k, v in self._kwargs.items())))


# TODO(John Sirois): document as the contract for targets fleshes out; especially the role of
# configurations.
class Target(Config):
  # An example of an addressable (is Serializable + has a name) that can cause graph walks.  The
  # only magic here are the fields wrapped with `addressables` which allow for mixed addresses and
  # embedded objects.  The addresses are tagged by being wrapped in the Addressed type which allows
  # a lazy resolution of the addressed and re-construction of this object with the fully resolved
  # properties later.

  def __init__(self, name=None, configurations=None, dependencies=None, **kwargs):
    super(Target, self).__init__(name=name,
                                 configurations=addressables(SubclassesOf(Config), configurations),
                                 dependencies=addressables(SubclassesOf(Target), dependencies),
                                 **kwargs)

  # Some convenience properties to give the class more form, but also not strictly needed.
  @property
  def configurations(self):
    return self._kwargs['configurations']

  @property
  def dependencies(self):
    return self._kwargs['dependencies']


class ApacheThriftConfig(Config, Validatable):
  # An example of a mixed-mode object - can be directly embedded without a name or else referenced
  # via address if both top-level and carrying a name.
  #
  # Also an example of a more constrained config object that has an explicit set of allowed fields
  # and that can have pydoc hung directly off the constructor to convey a fully accurate BUILD
  # dictionary entry.

  def __init__(self, name=None, version=None, strict=None, lang=None, options=None, **kwargs):
    super(ApacheThriftConfig, self).__init__(name=name,
                                             version=version,
                                             strict=strict,
                                             lang=lang,
                                             options=options,
                                             **kwargs)

  # An example of a validatable bit of config.
  def validate_concrete(self):
    if not self.version:
      self.report_validation_error('A thrift `version` is required.')
    if not self.lang:
      self.report_validation_error('A thrift gen `lang` is required.')


class PublishConfig(Config):
  # An example of addressable and addressable_mapping field wrappers.

  def __init__(self, default_repo, repos, name=None, **kwargs):
    super(PublishConfig, self).__init__(name=name,
                                        default_repo=addressable(Exactly(Config), default_repo),
                                        repos=addressable_mapping(Exactly(Config), repos),
                                        **kwargs)
