# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from hashlib import sha1

import six

from pants.build_graph.address import Address
from pants.util.meta import AbstractClass


class IntermediateTargetFactoryBase(AbstractClass):
  """Convenience factory which constructs an intermediate target with the appropriate attributes.

  For example, this makes the syntax:

  ```
      jar_library(name='gson',
        jars=[...],
      )

      target(name='foo',
        dependencies=[
          scoped(':gson', scope='runtime'),
        ],
      )
  ```

  Equivalent to:

  ```
      jar_library(name='gson',
        jars=[...],
      )

      target(name='gson-runtime',
        dependencies=[
          ':gson',
        ],
        scope='runtime',
      )

      target(name='foo',
        dependencies=[
          ':gson-runtime',
        ],
      )
  ```

  The syntax for this feature is experimental and may change in the future.
  """

  class ExpectedAddressError(Exception):
    """Thrown if an object that is not an address is used as the dependency spec."""

  def __init__(self, parse_context):
    self._parse_context = parse_context

  @property
  def intermediate_targets(self):
    if getattr(self.__class__, '_targets') is not None:
      return self.__class__._targets
    else:
      raise AttributeError('Subclass of {} should have class variable "{}"'.format(
        IntermediateTargetFactoryBase, '_targets'
      ))

  @property
  def extra_target_arguments(self):
    """Extra keyword arguments to pass to the target constructor."""
    return dict()

  def __call__(self, address, scope_str='intransitive'):
    """
    :param string address: A target address.
    :returns: The address of a synthetic intermediary target.
    """
    if not isinstance(address, six.string_types):
      raise self.ExpectedAddressError("Expected string address argument, got type {type}"
                                      .format(type=type(address)))

    address = Address.parse(address, self._parse_context.rel_path)
    # NB(gmalmquist): Ideally there should be a way to indicate that these targets are synthetic
    # and shouldn't show up in `./pants list` etc, because we really don't want people to write
    # handwritten dependencies on them. For now just give them names containing "-unstable-" as a
    # hint.
    hasher = sha1()
    hasher.update(str(address))
    hasher.update(scope_str)

    name = '{name}-unstable-{scope}-{index}'.format(
      name=address.target_name,
      scope=scope_str.replace(' ', '.'),
      index=hasher.hexdigest(),
    )

    if name not in self.intermediate_targets:
      self._parse_context.create_object(
        'target',
        name=name,
        dependencies=[address.spec],
        **self.extra_target_arguments
      )
      self.intermediate_targets[name] = self._parse_context.rel_path

    spec_path = self.intermediate_targets[name]
    return '{}:{}'.format(spec_path, name)
