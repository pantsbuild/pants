# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.util import topological_sort

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.errors import OptionsError


class ScopeHierarchy(object):
  """Gathers information about how scopes relate to each other.

  A scope inherits option values from its parent scope, as described below in compute_parent().
  A if an option on the parent scope is recursive, then it may also be overridden in the
  inner scope (non-recursive options have their values set on the inner scope, but they cannot
  be overridden there).
  """

  @classmethod
  def compute_parent(cls, scope, qualified):
    """Compute the scope that the given scope inherits option values from.

    If the scope is unqualified, this is simply the immediately enclosing scope.
    If the scope is qualified, this is the immediately enclosing scope of the unqualified scope,
    qualified.

    For example:
    - `foo.bar` inherits from `foo`, which inherits from the global scope.
    - `foo.bar.qualifier` inherits from `foo.qualifier`, which inherits from `qualifier`.
    - `qualifier` inherits from the global scope.

    :param scope: Return the option values for this scope.
    :param qualified: Whether the scope is qualified.
    """
    if qualified:
      parent, _, qualifier = scope.rpartition('.')
      if parent == '':
        ret = GLOBAL_SCOPE
      else:
        unqualified_parent = parent.rpartition('.')[0]
        ret = '{}.{}'.format(unqualified_parent, qualifier) if unqualified_parent else qualifier
    else:
      ret = scope.rpartition('.')[0]
    return ret

  def __init__(self):
    self._scope_to_parent = {
      GLOBAL_SCOPE: None
    }

  def register(self, scope, qualified=False):
    parent = self.compute_parent(scope, qualified)
    existing_parent = self._scope_to_parent.get(scope)
    if existing_parent and existing_parent != parent:
      raise OptionsError('Cannot re-add scope {0} with parent {1}, when it already had '
                         'parent {2}'.format(scope, parent, existing_parent))
    # Otherwise, no harm-no foul, so continue silently.
    self._scope_to_parent[scope] = parent

  def get_known_scopes(self):
    """Return the known scopes, sorted such that parents precede children."""
    tsorted = []
    for group in topological_sort(self._scope_to_parent):
      tsorted.extend(group)
    return tsorted

  def get_parent(self, scope):
    return self._scope_to_parent[scope]

  @property
  def scope_to_parent(self):
    return self._scope_to_parent
