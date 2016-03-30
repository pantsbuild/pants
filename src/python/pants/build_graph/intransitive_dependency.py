# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.build_graph.address import Address


class IntermediateTargetFactoryBase(object):
  """Base class for factories to create intermediate targets for inclusion in a dependencies list.
  """

  class ExpectedAddressError(Exception):
    """Thrown if an object that is not an address is used as the dependency spec."""

  def __init__(self, parse_context):
    self._parse_context = parse_context
    self.__index = 0

  @property
  def extra_target_arguments(self):
    """Extra keyword arguments to pass to the target constructor."""
    return {}

  def __call__(self, address):
    """
    :param string address: A target address.
    :returns: The address of a synthetic intermediary target.
    """
    if not isinstance(address, six.string_types):
      raise self.ExpectedAddressError("Expected string address argument, got type {type}"
                                      .format(type(address)))
    address = Address.parse(address, self._parse_context.rel_path)
    self.__index += 1
    # NB(gmalmquist): Ideally there should be a way to indicate that these targets are synthetic
    # and shouldn't show up in `./pants list` etc, because we really don't want people to write
    # handwritten dependencies on them. For now just give them names containing "-unstable-" as a
    # hint.
    name = '{name}-unstable-intransitive-{index}'.format(
      name=address.target_name,
      index=self.__index,
    )
    self._parse_context.create_object(
      'target',
      name=name,
      dependencies=[address.spec],
      **self.extra_target_arguments
    )
    return ':{}'.format(name)


class IntransitiveDependencyFactory(IntermediateTargetFactoryBase):
  """Creates a dependency which is intransitive.

  This dependency will not be seen by dependees of this target. The syntax for this feature is
  experimental and may change in the future.
  """

  @property
  def extra_target_arguments(self):
    return dict(_transitive=False)


class ProvidedDependencyFactory(IntermediateTargetFactoryBase):
  """Creates an intransitive dependency with scope='compile test'.

  This mirrors the behavior of the "provided" scope found in other build systems, such as Gradle,
  Maven, and IntelliJ.

  The syntax for this feature is experimental and may change in the future.
  """

  @property
  def extra_target_arguments(self):
    return dict(_transitive=False, scope='compile test')
