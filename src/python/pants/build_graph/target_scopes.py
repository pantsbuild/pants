# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.build_graph.intermediate_target_factory import IntermediateTargetFactoryBase


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
      raise ValueError('include_scopes must be a Scope instance.')
    if exclude_scopes is not None and not isinstance(exclude_scopes, Scope):
      raise ValueError('exclude_scopes must be a Scope instance.')
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


class ScopedDependencyFactory(IntermediateTargetFactoryBase):
  """Creates a dependency with the given scope.

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

  def __init__(self, parse_context):
    super(ScopedDependencyFactory, self).__init__(parse_context)
    self._scope = None

  @property
  def extra_target_arguments(self):
    """Extra keyword arguments to pass to the target constructor."""
    return dict(scope=self._scope) if self._scope else dict()

  def __call__(self, address, scope=None):
    """
    :param string address: A target address.
    :param string scope: The scope of this dependency.
    :returns: The address of a synthetic intermediary target.
    """
    scope = Scope(scope)
    self._scope = str(scope)
    return self._create_intermediate_target(address, self._scope)
