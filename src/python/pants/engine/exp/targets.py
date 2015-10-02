# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.engine.exp.addressable import addressable, addressable_mapping, addressables
from pants.engine.exp.serializable import Serializable


# TODO(John Sirois): Find a better - non-overloaded - name for this.
class Config(Serializable):
  """A serializable object describing some bit of build configuration.

  All build configuration data is composed of basic python builtin types and higher-level config
  objects that aggregate configuration data.  Config objects can carry a name in which case they
  become addressable and can be reused.
  """

  def __init__(self, **kwargs):
    """Creates a new configuration data blob.

    :param **kwargs: The configuration parameters.
    """
    self._kwargs = kwargs
    self._hashable_key = None

  @property
  def name(self):
    """Return the name of this object if any.

    In general config objects need not be named, in which case they are generally embedded objects;
    ie: attributes values of enclosing named config objects.  Any top-level config object though
    will carry a unique name (in the config object's enclosing namespace) that can be used to
    address it.
    """
    return self._kwargs.get('name')

  @property
  def typename(self):
    """Returns the type name this target was constructed via.

    For a target read from a BUILD file, this will be target alias, like 'java_library'.
    For a target constructed in memory, this will be the simple class name, like 'JavaLibrary'.

    The end result is that the type alias should be the most natural way to refer to this target's
    type to the author of the target instance.

    :rtype: string
    """
    return self._kwargs.get('typename', type(self).__name__)

  def _asdict(self):
    return self._kwargs.copy()

  def _key(self):
    if self._hashable_key is None:
      self._hashable_key = sorted((k, v) for k, v in self._kwargs.items() if k != 'typename')
    return self._hashable_key

  def __hash__(self):
    return hash(self._key())

  def __eq__(self, other):
    return isinstance(other, Config) and self._key() == other._key()

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
                                 configurations=addressables(Config, configurations),
                                 dependencies=addressables(Target, dependencies),
                                 **kwargs)

  # Some convenience properties to give the class more form, but also not strictly needed.
  @property
  def configurations(self):
    return self._kwargs['configurations']

  @property
  def dependencies(self):
    return self._kwargs['dependencies']


class ApacheThriftConfig(Config):
  # An example of a mixed-mode object - can be directly embedded without a name or else referenced
  # via address if both top-level and carrying a name.
  #
  # Also an example of a more constrained config object that has an explicit set of allowed fields
  # and that can have pydoc hung directly off the constructor to convey a fully accurate BUILD
  # dictionary entry with no hierarchy walking or ignoring of "special" fields - there are no
  # special fields.

  def __init__(self, name=None, version=None, strict=None, lang=None, options=None, **kwargs):
    super(ApacheThriftConfig, self).__init__(name=name,
                                             version=version,
                                             strict=strict,
                                             lang=lang,
                                             options=options,
                                             **kwargs)


class PublishConfig(Config):
  # An example of addressable and addressable_mapping.

  def __init__(self, default_repo, repos, name=None, **kwargs):
    super(PublishConfig, self).__init__(name=name,
                                        default_repo=addressable(Config, default_repo),
                                        repos=addressable_mapping(Config, repos),
                                        **kwargs)
