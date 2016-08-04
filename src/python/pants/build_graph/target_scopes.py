# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.build_graph.address import Address


class Scope(frozenset):
  """Represents a set of dependency scope names.

  It is the responsibility of individual tasks to read and respect these scopes by using functions
  such as target.closure() and BuildGraph.closure().
  """

  @classmethod
  def _parse(cls, scope):
    """Parses the input scope into a normalized set of strings.

    :param scope: A string or tuple containing zero or more scope names.
    :return: A set of scope name strings, or a tuple with the default scope name.
    :rtype: set
    """
    if not scope:
      return ('default',)
    if isinstance(scope, six.string_types):
      scope = scope.split(' ')
    scope = {str(s).lower() for s in scope if s}
    return scope or ('default',)

  def __new__(cls, scope):
    return super(Scope, cls).__new__(cls, cls._parse(scope))

  def in_scope(self, exclude_scopes=None, include_scopes=None):
    """Whether this scope should be included by the given inclusion and exclusion rules.

    :param Scope exclude_scopes: An optional Scope containing scope names to exclude. None (the
      default value) indicates that no filtering should be done based on exclude_scopes.
    :param Scope include_scopes: An optional Scope containing scope names to include. None (the
      default value) indicates that no filtering should be done based on include_scopes.
    :return: True if none of the input scopes are in `exclude_scopes`, and either (a) no include
      scopes are provided, or (b) at least one input scope is included in the `include_scopes` list.
    :rtype: bool
    """
    if include_scopes is not None and not isinstance(include_scopes, Scope):
      raise ValueError('include_scopes must by a Scope instance.')
    if exclude_scopes is not None and not isinstance(exclude_scopes, Scope):
      raise ValueError('exclude_scopes must by a Scope instance.')
    if exclude_scopes and any(s in exclude_scopes for s in self):
      return False
    if include_scopes and not any(s in include_scopes for s in self):
      return False
    return True

  def __add__(self, other):
    return self | other

  def __str__(self):
    return ' '.join(sorted(self))


class Scopes(object):
  """Default scope constants."""

  DEFAULT = Scope('DEFAULT')
  # The `FORCED` scope is equivalent to DEFAULT, but additionally declares that a dep
  # might not be detected as used at compile time, and should thus always be considered
  # to have been used at compile time.
  FORCED = Scope('FORCED')
  COMPILE = Scope('COMPILE')
  RUNTIME = Scope('RUNTIME')
  TEST = Scope('TEST')

  DEFAULT_OR_FORCED = DEFAULT | FORCED

  JVM_COMPILE_SCOPES = DEFAULT_OR_FORCED | COMPILE
  JVM_RUNTIME_SCOPES = DEFAULT_OR_FORCED | RUNTIME
  JVM_TEST_SCOPES = DEFAULT_OR_FORCED | RUNTIME | TEST


class ScopedDependencyFactory(object):
  """Convenience factory which constructs an intermediary target with the appropriate attributes.

  This makes the syntax:

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
    self.__index = 0

  def __call__(self, address, scope=None):
    """
    :param string scope: The scope of this dependency.
    :param string address: A target address.
    :returns: The address of a synthetic intermediary target.
    """
    if not isinstance(address, six.string_types):
      raise self.ExpectedAddressError("Expected string address argument, got type {type}"
                                      .format(type(address)))
    scope = Scope(scope)
    address = Address.parse(address, self._parse_context.rel_path)
    self.__index += 1
    # NB(gmalmquist): Ideally we should hide this from `./pants list` etc somehow (see note in
    # intransitive_dependency.py dealing with the same issue).
    name = '{name}-unstable-{scope}-{index}'.format(
      name=address.target_name,
      scope=str(scope).replace(' ', '.'),
      index=self.__index,
    )
    self._parse_context.create_object(
      'target',
       name=name,
       scope=str(scope),
       dependencies=[address.spec],
    )
    return ':{}'.format(name)
